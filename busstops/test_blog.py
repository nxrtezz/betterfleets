from django.contrib.auth.models import Permission
from django.test import TestCase
from django.utils import timezone

from accounts.models import User

from .models import BlogPost, BlogTag


class BlogWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.add_permission = Permission.objects.get(codename="add_blogpost")
        cls.change_permission = Permission.objects.get(codename="change_blogpost")
        cls.editor = User.objects.create_user(
            username="editor",
            email="editor@example.com",
            password="secret",
        )
        cls.editor.user_permissions.add(cls.add_permission, cls.change_permission)
        cls.viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="secret",
        )
        cls.tag = BlogTag.objects.create(name="Launch")
        cls.live_post = BlogPost.objects.create(
            title="Launch update",
            slug="launch-update",
            excerpt="Short summary",
            body="## What's new\n\n- Better writing flow\n- Cleaner templates",
            published=True,
            published_at=timezone.now(),
        )
        cls.live_post.tags.add(cls.tag)
        cls.draft_post = BlogPost.objects.create(
            title="Draft roadmap",
            slug="draft-roadmap",
            body="Internal draft only",
            published=False,
        )

    def test_public_blog_hides_drafts(self):
        response = self.client.get("/blog")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Launch update")
        self.assertNotContains(response, "Draft roadmap")

    def test_editor_can_open_blog_manager(self):
        self.client.force_login(self.editor)

        response = self.client.get("/blog/manage")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manage blog posts")
        self.assertContains(response, "Write a new post")

    def test_editor_can_create_draft_post_outside_admin(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            "/blog/write",
            {
                "title": "New fleet note",
                "slug": "new-fleet-note",
                "excerpt": "A short intro",
                "tags_text": "Fleet, Pride",
                "body": "## Heading\n\n- One\n- Two",
                "save_draft": "1",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        post = BlogPost.objects.get(slug="new-fleet-note")
        self.assertFalse(post.published)
        self.assertEqual(post.tags.count(), 2)
        self.assertContains(response, "Manage blog posts")

    def test_editor_can_publish_post_outside_admin(self):
        self.client.force_login(self.editor)

        response = self.client.post(
            "/blog/write",
            {
                "title": "Published note",
                "slug": "published-note",
                "excerpt": "Live now",
                "tags_text": "Launch",
                "body": "## Live heading\n\nParagraph body",
                "publish": "1",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        post = BlogPost.objects.get(slug="published-note")
        self.assertTrue(post.published)
        self.assertIsNotNone(post.published_at)
        self.assertContains(response, "Live heading")

    def test_editor_can_preview_draft_detail(self):
        self.client.force_login(self.editor)

        response = self.client.get("/blog/draft-roadmap")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Draft preview")

    def test_public_cannot_open_draft_detail(self):
        response = self.client.get("/blog/draft-roadmap")

        self.assertEqual(response.status_code, 404)

    def test_blog_body_renders_headings_and_lists(self):
        response = self.client.get("/blog/launch-update")

        self.assertContains(response, "<h2>What&#x27;s new</h2>", html=False)
        self.assertContains(response, "<li>Better writing flow</li>", html=False)

