#!/usr/bin/env python
"""
Script to list all fields in all Django models in the betterfleets project.
Run with: python list_model_fields.py
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'buses.settings')
django.setup()

from django.apps import apps


def get_field_info(field):
    """Get detailed information about a model field."""
    field_type = field.__class__.__name__
    field_info = {
        'name': field.name,
        'type': field_type,
        'verbose_name': str(field.verbose_name) if hasattr(field, 'verbose_name') else '',
        'help_text': field.help_text if hasattr(field, 'help_text') else '',
        'null': field.null if hasattr(field, 'null') else None,
        'blank': field.blank if hasattr(field, 'blank') else None,
        'default': repr(field.default) if hasattr(field, 'default') and field.default != django.db.models.NOT_PROVIDED else '',
        'choices': str(field.choices) if hasattr(field, 'choices') and field.choices else '',
        'max_length': field.max_length if hasattr(field, 'max_length') else None,
        'primary_key': field.primary_key if hasattr(field, 'primary_key') else False,
        'unique': field.unique if hasattr(field, 'unique') else False,
        'editable': field.editable if hasattr(field, 'editable') else True,
    }

    # Handle foreign keys
    if hasattr(field, 'related_model') and field.related_model:
        field_info['related_model'] = str(field.related_model)
        field_info['related_name'] = field.remote_field.related_name if hasattr(field.remote_field, 'related_name') else ''

    # Handle many-to-many
    if hasattr(field, 'many_to_many') and field.many_to_many:
        field_info['many_to_many'] = True
        if hasattr(field, 'related_model') and field.related_model:
            field_info['related_model'] = str(field.related_model)

    return field_info


def list_all_model_fields():
    """List all fields for all models in the project."""
    output = []

    for app_config in apps.get_app_configs():
        app_name = app_config.name
        models = app_config.get_models()

        if not models:
            continue

        output.append(f"\n{'='*80}")
        output.append(f"APP: {app_name}")
        output.append(f"{'='*80}\n")

        for model in models:
            model_name = model.__name__
            table_name = model._meta.db_table

            output.append(f"Model: {model_name}")
            output.append(f"Table: {table_name}")
            output.append(f"{'-'*80}")

            fields = model._meta.get_fields()
            for field in fields:
                # Skip reverse relations (they're not actual fields in the table)
                if field.auto_created:
                    continue

                field_info = get_field_info(field)

                output.append(f"\n  Field: {field_info['name']}")
                output.append(f"    Type: {field_info['type']}")
                if field_info['verbose_name']:
                    output.append(f"    Verbose Name: {field_info['verbose_name']}")
                if field_info['help_text']:
                    output.append(f"    Help Text: {field_info['help_text']}")
                if field_info['null'] is not None:
                    output.append(f"    Null: {field_info['null']}")
                if field_info['blank'] is not None:
                    output.append(f"    Blank: {field_info['blank']}")
                if field_info['default']:
                    output.append(f"    Default: {field_info['default']}")
                if field_info['choices']:
                    output.append(f"    Choices: {field_info['choices']}")
                if field_info['max_length']:
                    output.append(f"    Max Length: {field_info['max_length']}")
                if field_info['primary_key']:
                    output.append(f"    Primary Key: {field_info['primary_key']}")
                if field_info['unique']:
                    output.append(f"    Unique: {field_info['unique']}")
                if field_info['related_model']:
                    output.append(f"    Related Model: {field_info['related_model']}")
                if field_info['related_name']:
                    output.append(f"    Related Name: {field_info['related_name']}")
                if field_info.get('many_to_many'):
                    output.append(f"    Many-to-Many: Yes")

            output.append(f"\n{'-'*80}\n")

    return '\n'.join(output)


if __name__ == '__main__':
    output = list_all_model_fields()
    print(output)

    # Also write to file
    with open('model_fields.txt', 'w', encoding='utf-8') as f:
        f.write(output)

    print("\n\nOutput also written to model_fields.txt")
