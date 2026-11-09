from django import forms


def validate_phone_number(phone):
    import re

    if not re.fullmatch(r'\+?\d+', phone):
        raise forms.ValidationError('Phone number may only contain digits and an optional leading +.')

    digit_count = len(phone.lstrip('+'))
    if digit_count < 11:
        raise forms.ValidationError('Phone number must have at least 11 digits.')