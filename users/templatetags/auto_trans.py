from django import template
from django.utils.translation import gettext as _  # Translation function
from bs4 import BeautifulSoup, Comment

register = template.Library()

class AutoTransNode(template.Node):
    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        output = self.nodelist.render(context)
        soup = BeautifulSoup(output, 'html.parser')

        # Function to process text nodes
        def process_text(text):
            if not text.strip():  # Skip empty or whitespace-only text
                return text

            # Skip if parent is script, style, or has notranslate class
            if (text.parent.name in ['script', 'style'] or
                isinstance(text, Comment) or
                any('notranslate' in ancestor.get('class', [])
                    for ancestor in text.parents)):
                return text

            # Translate the text using gettext function
            return _(text.string.strip())

        # Find all text nodes and process them
        for text in soup.find_all(text=True):
            if text.strip() and not any('notranslate' in ancestor.get('class', []) for ancestor in text.parents):
                processed_text = process_text(text)
                text.replace_with(processed_text)

        return str(soup)

@register.tag(name="auto_trans")
def auto_trans(parser, token):
    nodelist = parser.parse(('endauto_trans',))
    parser.delete_first_token()
    return AutoTransNode(nodelist)
