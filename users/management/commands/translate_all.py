from django.core.management.base import BaseCommand
import requests
import polib
import os
from pathlib import Path
import subprocess
import sys


class Command(BaseCommand):
    help = 'Translate messages to Spanish and French with enhanced HTML detection'

    def add_arguments(self, parser):
        parser.add_argument(
            '--regenerate',
            action='store_true',
            help='Force regeneration of .po files',
        )

    def handle(self, *args, **options):
        try:
            from django.conf import settings
            api_key = settings.CLOUD_API_KEY
        except Exception as e:
            self.stderr.write(f"Error loading settings: {str(e)}")
            return

        languages = ['es', 'fr']

        # Get the base directory
        base_dir = Path(settings.BASE_DIR)
        locale_dir = base_dir / 'locale'

        # Ensure locale directory exists
        locale_dir.mkdir(exist_ok=True)

        for lang in languages:
            self.stdout.write(f"\nProcessing {lang}...")

            # Create language directory if it doesn't exist
            lang_dir = locale_dir / lang / 'LC_MESSAGES'
            lang_dir.mkdir(parents=True, exist_ok=True)

            po_path = lang_dir / 'django.po'

            if options['regenerate'] or not po_path.exists():
                self.stdout.write(f"Generating .po file for {lang}...")

                try:
                    # Run makemessages
                    subprocess.run([
                        sys.executable,
                        'manage.py',
                        'makemessages',
                        '-l', lang,
                        '--ignore=venv/*',
                        '--ignore=**/migrations/*',
                        '-d', 'django',
                        '--add-location=file',
                    ], check=True)
                except subprocess.CalledProcessError as e:
                    self.stderr.write(f"Error running makemessages: {e}")
                    continue

            if not po_path.exists():
                self.stderr.write(f"No .po file found at {po_path}")
                continue

            try:
                po = polib.pofile(str(po_path))
            except Exception as e:
                self.stderr.write(f"Error reading .po file: {e}")
                continue

            untranslated_count = len(po.untranslated_entries())
            if untranslated_count == 0:
                self.stdout.write(f"No untranslated strings found for {lang}")
                continue

            self.stdout.write(f"Found {untranslated_count} untranslated strings")

            for entry in po.untranslated_entries():
                if not entry.msgid:
                    continue

                try:
                    url = f"https://translation.googleapis.com/language/translate/v2?key={api_key}"
                    data = {
                        'q': entry.msgid,
                        'target': lang,
                        'format': 'html'
                    }
                    response = requests.post(url, data=data)
                    response.raise_for_status()

                    translated_text = response.json()['data']['translations'][0]['translatedText']
                    entry.msgstr = translated_text
                    self.stdout.write(f'Translated: {entry.msgid} → {entry.msgstr}')

                except Exception as e:
                    self.stderr.write(f"Error translating '{entry.msgid}': {e}")
                    continue

            try:
                po.save()
                self.stdout.write(f"Saved translations for {lang}")
            except Exception as e:
                self.stderr.write(f"Error saving .po file: {e}")
                continue

        try:
            subprocess.run([
                sys.executable,
                'manage.py',
                'compilemessages'
            ], check=True)
            self.stdout.write(self.style.SUCCESS("\nTranslations completed and compiled!"))
        except subprocess.CalledProcessError as e:
            self.stderr.write(f"Error compiling messages: {e}")