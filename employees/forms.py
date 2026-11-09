from django import forms
from django.contrib.auth import get_user_model
from datetime import date
from .models import Employee
from common.validators import validate_phone_number

User = get_user_model()

class EmployeeAccountForm(forms.Form):
    """Step 1: just creates the login (user). No HR profile yet."""
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=150, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def save(self):
        data = self.cleaned_data
        user = User(
            username=data['username'],
            first_name=data['first_name'],
            last_name=data['last_name'],
            email=data['email'],
            user_type=User.UserType.EMPLOYEE,
        )
        user.set_password(data['password'])
        user.save()
        return user


class EmployeeGeneralInfoForm(forms.Form):
    """Step 2: 'Add Information' the first time, 'Update General Information' after."""
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = forms.CharField(max_length=150, required=False, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))

    dob = forms.DateField(label='Date of Birth',widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    phone = forms.CharField(max_length=20, widget=forms.TextInput(attrs={'class': 'form-control'}))
    present_address = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}))
    permanent_address = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}))
    designation = forms.CharField(max_length=100, widget=forms.TextInput(attrs={'class': 'form-control'}))
    salary = forms.DecimalField(max_digits=10, decimal_places=2, widget=forms.NumberInput(attrs={'class': 'form-control'}))
    photo = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    id_card_front = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))
    id_card_back = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control'}))

    def __init__(self, *args, user=None, employee=None, **kwargs):
        self.user = user
        self.employee = employee
        super().__init__(*args, **kwargs)
        if user:
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email
        if employee:
            self.fields['dob'].initial = employee.dob
            self.fields['phone'].initial = employee.phone
            self.fields['present_address'].initial = employee.present_address
            self.fields['permanent_address'].initial = employee.permanent_address
            self.fields['designation'].initial = employee.designation
            self.fields['salary'].initial = employee.salary
        else:
            self.fields['photo'].required = True
            self.fields['id_card_front'].required = True
            self.fields['id_card_back'].required = True
    def clean_dob(self):
        dob = self.cleaned_data['dob']
        today = date.today()

        if dob > today:
            raise forms.ValidationError('Date of birth cannot be in the future.')

        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < 15:
            raise forms.ValidationError('Employee must be at least 15 years old.')

        return dob

    def clean_phone(self):
        phone = self.cleaned_data['phone']
        validate_phone_number(phone)
        return phone
    def save(self):
        data = self.cleaned_data

        self.user.first_name = data['first_name']
        self.user.last_name = data['last_name']
        self.user.email = data['email']
        self.user.save()

        employee = self.employee or Employee(user=self.user)
        employee.dob = data['dob']
        employee.phone = data['phone']
        employee.present_address = data['present_address']
        employee.permanent_address = data['permanent_address']
        employee.designation = data['designation']
        employee.salary = data['salary']
        if data['photo']:
            employee.photo = data['photo']
        if data['id_card_front']:
            employee.id_card_front = data['id_card_front']
        if data['id_card_back']:
            employee.id_card_back = data['id_card_back']
        employee.save()
        return employee

class EmployeeCredentialsForm(forms.Form):
    """Update Credentials: active/inactive toggle + optional password change."""
    is_active = forms.BooleanField(required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}), required=False)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user:
            self.fields['is_active'].initial = user.is_active

    def save(self):
        data = self.cleaned_data
        self.user.is_active = data['is_active']
        if data['password']:
            self.user.set_password(data['password'])
        self.user.save()
        return self.user