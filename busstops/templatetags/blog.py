from django import template
from django.utils.html import escape, urlize
from django.utils.safestring import mark_safe

register = template.Library()


def _format_inline(text: str) -> str:
    return urlize(escape(text), nofollow=True)


@register.filter(is_safe=True)
def render_blog_body(value):
    lines = (value or "").splitlines()
    html = []
    paragraph = []
    bullets = []

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            html.append(f"<p>{_format_inline(' '.join(paragraph))}</p>")
            paragraph = []

    def flush_bullets():
        nonlocal bullets
        if bullets:
            html.append(
                "<ul>" + "".join(f"<li>{_format_inline(item)}</li>" for item in bullets) + "</ul>"
            )
            bullets = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_bullets()
            continue
        if line.startswith("### "):
            flush_paragraph()
            flush_bullets()
            html.append(f"<h3>{_format_inline(line[4:])}</h3>")
            continue
        if line.startswith("## "):
            flush_paragraph()
            flush_bullets()
            html.append(f"<h2>{_format_inline(line[3:])}</h2>")
            continue
        if line.startswith("- "):
            flush_paragraph()
            bullets.append(line[2:])
            continue
        flush_bullets()
        paragraph.append(line)

    flush_paragraph()
    flush_bullets()
    return mark_safe("".join(html))
