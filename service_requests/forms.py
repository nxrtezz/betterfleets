from django import forms
from django.contrib.auth import get_user_model
from .models import Request, RequestComment, RequestCategory

User = get_user_model()


class RequestForm(forms.ModelForm):
    """Form for creating and editing requests."""
    
    class Meta:
        model = Request
        fields = [
            "title", "description", "category", "vehicle", "service",
            "operator", "vehicle_type", "livery", "fleet_number",
            "registration", "route", "expected_behaviour"
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "placeholder": "Request title"}),
            "description": forms.Textarea(attrs={
                "class": "textarea",
                "rows": 4,
                "placeholder": "Describe your request in detail..."
            }),
            "category": forms.Select(attrs={"class": "select"}),
            "expected_behaviour": forms.Textarea(attrs={
                "class": "textarea",
                "rows": 3,
                "placeholder": "What behaviour do you expect?"
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add dynamic field visibility based on category
        if self.instance and self.instance.pk:
            self.fields["category"].disabled = True  # Don't allow changing category after creation
    
    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get("category")
        
        # Validate required fields based on category
        if category == RequestCategory.VEHICLE:
            if not cleaned_data.get("vehicle") and not (
                cleaned_data.get("fleet_number") or cleaned_data.get("registration")
            ):
                raise forms.ValidationError(
                    "Vehicle requests must specify a vehicle, fleet number, or registration."
                )
        elif category == RequestCategory.SERVICE:
            if not cleaned_data.get("service") and not cleaned_data.get("route"):
                raise forms.ValidationError(
                    "Service requests must specify a service or route."
                )
        elif category == RequestCategory.OPERATOR:
            if not cleaned_data.get("operator"):
                raise forms.ValidationError(
                    "Operator requests must specify an operator."
                )
        elif category == RequestCategory.VEHICLE_TYPE:
            if not cleaned_data.get("vehicle_type"):
                raise forms.ValidationError(
                    "Vehicle type requests must specify a vehicle type."
                )
        elif category == RequestCategory.LIVERY:
            if not cleaned_data.get("livery"):
                raise forms.ValidationError(
                    "Livery requests must specify a livery."
                )
        elif category == RequestCategory.SITE_FEATURE:
            if not cleaned_data.get("expected_behaviour"):
                raise forms.ValidationError(
                    "Feature requests should describe expected behaviour."
                )
        
        return cleaned_data


class RequestCommentForm(forms.ModelForm):
    """Form for adding comments to requests."""
    
    class Meta:
        model = RequestComment
        fields = ["content"]
        widgets = {
            "content": forms.Textarea(attrs={
                "class": "textarea",
                "rows": 3,
                "placeholder": "Add a comment..."
            })
        }


class RequestStatusForm(forms.ModelForm):
    """Form for changing request status (admin use)."""
    
    class Meta:
        model = Request
        fields = ["status"]
        widgets = {
            "status": forms.Select(attrs={"class": "select"})
        }
