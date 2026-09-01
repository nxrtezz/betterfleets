from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.urls import reverse
import requests
import re
import hashlib
from django.core.files.base import ContentFile

from .models import Request, RequestComment, RequestHistory, RequestCategory, RequestStatus
from .forms import RequestForm, RequestCommentForm, RequestStatusForm


def get_flickr_image_url(flickr_url):
    """Extract the actual image URL and author from a Flickr photo page."""
    try:
        response = requests.get(flickr_url, timeout=10)
        response.raise_for_status()
        
        # Use regex to find the image URL and alt text in the noscript tag
        # Pattern to match: <img src="..." alt="...">
        pattern = r'<img[^>]*src=["\']([^"\']*staticflickr[^"\']*)["\'][^>]*alt=["\']([^"\']*)["\']'
        matches = re.findall(pattern, response.text)
        
        if matches:
            image_url, alt_text = matches[0]
            # Ensure it has the protocol
            if image_url.startswith('//'):
                image_url = 'https:' + image_url
            
            # Extract author from alt text (format: "... | by author")
            author = None
            if alt_text and '| by' in alt_text:
                author = alt_text.split('| by')[-1].strip()
            elif alt_text:
                # Fallback: use the entire alt text if no "| by" pattern
                author = alt_text.strip()
            
            # If still no author, try to extract from URL
            if not author:
                url_match = re.search(r'/photos/([^/]+)/', flickr_url)
                if url_match:
                    author = url_match.group(1)
            
            return image_url, author or "Unknown"
        
        return None, None
    except Exception as e:
        print(f"Error extracting Flickr image URL: {e}")
        return None, None


class RequestListView(ListView):
    """List all requests with filtering."""
    model = Request
    template_name = "service_requests/request_list.html"
    context_object_name = "requests"
    paginate_by = 25
    
    def get_queryset(self):
        queryset = Request.objects.select_related(
            "author", "vehicle", "service", "operator", "vehicle_type", "livery"
        )
        
        # Filter by category
        category = self.request.GET.get("category")
        if category:
            queryset = queryset.filter(category=category)
        
        # Filter by status
        status = self.request.GET.get("status")
        if status:
            queryset = queryset.filter(status=status)
        
        # Filter by author
        author = self.request.GET.get("author")
        if author:
            queryset = queryset.filter(author_id=author)
        
        # Search
        search = self.request.GET.get("search")
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(description__icontains=search)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = RequestCategory.choices
        context["statuses"] = RequestStatus.choices
        context["current_category"] = self.request.GET.get("category")
        context["current_status"] = self.request.GET.get("status")
        context["current_search"] = self.request.GET.get("search", "")
        return context


class RequestDetailView(DetailView):
    """Detail view for a single request."""
    model = Request
    template_name = "service_requests/request_detail.html"
    context_object_name = "request"
    
    def get_queryset(self):
        return Request.objects.select_related(
            "author", "resolved_by", "vehicle", "service", "operator", 
            "vehicle_type", "livery"
        ).prefetch_related("comments__author", "timeline")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["comment_form"] = RequestCommentForm()
        return context


class RequestCreateView(LoginRequiredMixin, CreateView):
    """Create a new request."""
    model = Request
    form_class = RequestForm
    template_name = "service_requests/request_form.html"
    
    def form_valid(self, form):
        form.instance.author = self.request.user
        response = super().form_valid(form)
        
        # Create history entry
        RequestHistory.objects.create(
            request=self.object,
            user=self.request.user,
            action="created",
            description=f"Request created by {self.request.user.get_display_name()}"
        )
        
        messages.success(self.request, "Your request has been submitted successfully.")
        return response


class RequestUpdateView(LoginRequiredMixin, UpdateView):
    """Update an existing request."""
    model = Request
    form_class = RequestForm
    template_name = "service_requests/request_form.html"
    
    def get_queryset(self):
        return Request.objects.filter(author=self.request.user)
    
    def form_valid(self, form):
        response = super().form_valid(form)
        
        # Create history entry
        RequestHistory.objects.create(
            request=self.object,
            user=self.request.user,
            action="updated",
            description=f"Request updated by {self.request.user.get_display_name()}"
        )
        
        messages.success(self.request, "Your request has been updated successfully.")
        return response


@login_required
def add_comment(request, request_id):
    """Add a comment to a request."""
    req = get_object_or_404(Request, id=request_id)
    
    if request.method == "POST":
        form = RequestCommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.request = req
            comment.author = request.user
            comment.save()
            
            # Create history entry
            RequestHistory.objects.create(
                request=req,
                user=request.user,
                action="commented",
                description=f"Comment added by {request.user.get_display_name()}"
            )
            
            messages.success(request, "Your comment has been added.")
    
    return redirect("service_requests:detail", id=request_id)


@login_required
def change_status(request, request_id):
    """Change the status of a request (admin/staff only)."""
    if not request.user.is_staff:
        messages.error(request, "You don't have permission to change request status.")
        return redirect("service_requests:detail", id=request_id)
    
    req = get_object_or_404(Request, id=request_id)
    
    if request.method == "POST":
        form = RequestStatusForm(request.POST, instance=req)
        if form.is_valid():
            old_status = req.get_status_display()
            form.save()
            new_status = req.get_status_display()
            
            if req.status == RequestStatus.RESOLVED:
                req.resolved_by = request.user
                req.save(update_fields=["resolved_by"])
                
                # Handle photo request approval
                if req.category == RequestCategory.PHOTO and req.photo_url and req.vehicle:
                    try:
                        from photos.models import Photo
                        
                        # Extract the actual image URL and author from Flickr page
                        image_url, author = get_flickr_image_url(req.photo_url)
                        if not image_url:
                            messages.error(request, f"Request status changed to {new_status}, but could not extract image URL from Flickr page.")
                            return redirect("service_requests:detail", id=request_id)
                        
                        # Download the image
                        image_response = requests.get(image_url, timeout=10)
                        image_response.raise_for_status()
                        
                        # Create the photo
                        photo = Photo()
                        photo.user = request.user
                        photo.author = author  # Set the author from alt text
                        
                        # Extract photo ID for caption if possible
                        photo_id_match = re.search(r'/photos/[^/]+/(\d+)', req.photo_url)
                        if photo_id_match:
                            photo_id = photo_id_match.group(1)
                            photo.caption = f"Photo {photo_id}"
                        
                        # Save the image first to prevent automatic Flickr download
                        sha1 = hashlib.sha1(usedforsecurity=False)
                        sha1.update(image_response.content)
                        photo.image.save(f"{sha1.hexdigest()}.jpg", ContentFile(image_response.content))
                        
                        # Now set the flickr_url after image is saved to prevent automatic download
                        photo.flickr_url = req.photo_url
                        
                        photo.save()
                        
                        # Add to vehicle
                        photo.vehicles.add(req.vehicle)
                        
                        messages.success(request, f"Request status changed to {new_status}. Photo added successfully.")
                    except Exception as e:
                        messages.error(request, f"Request status changed to {new_status}, but failed to add photo: {str(e)}")
                    return redirect("service_requests:detail", id=request_id)
            
            # Create history entry
            RequestHistory.objects.create(
                request=req,
                user=request.user,
                action="status_changed",
                description=f"Status changed from {old_status} to {new_status}"
            )
            
            messages.success(request, f"Request status changed to {new_status}.")
    
    return redirect("service_requests:detail", id=request_id)
