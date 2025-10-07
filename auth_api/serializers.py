from rest_framework import serializers
from admin_part.models import CustomUser, EmailCenter
from .utils import generate_otp, send_otp_via_email
from .models import EmailOTP,UserDevice
from admin_part.models import UserProfile
from .models import *
from .utils import send_otp

class UserRegistrationSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(write_only=True)
    phone_number = serializers.CharField(
        max_length=15,
    )

    class Meta:
        model = CustomUser
        fields = ['full_name', 'email', 'dob', 'phone_number', 'password', 'confirm_password']
        extra_kwargs = {
            'password': {'write_only': True},
        }

    # Validate authorized email
    def validate_email(self, value):
        if not EmailCenter.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is not authorized for registration.")
        return value

    # Validate unique phone number
    def validate_phone_number(self, value):
        if CustomUser.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("This phone number is already registered.")
        return value

    # Validate password confirmation
    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs

    # Create user
    def create(self, validated_data):
        validated_data.pop('confirm_password')
        email = validated_data['email']
        email_center = EmailCenter.objects.get(email=email)
        validated_data['level_id'] = email_center
        user = CustomUser.objects.create_user(**validated_data)
        return user

class SendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        if not CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is not registered.")
        return value

    def create(self, validated_data):
        email = validated_data['email']
        otp = generate_otp()

        EmailOTP.objects.filter(email=email).delete()  # Clear old OTPs
        EmailOTP.objects.create(email=email, otp=otp)

        send_otp_via_email(email, otp)
        return {"message": "OTP sent successfully to email."}
    
class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)

    def validate(self, data):
        email = data['email'].lower().strip()
        otp = data['otp'].strip()

        print("Validating OTP for email:", email)
        print("Received OTP:", otp)

        # Removed is_verified=False for debugging
        records = EmailOTP.objects.filter(
            email__iexact=email,
            otp=otp
        ).order_by('-created_at')

        print("Matching OTP records:", records)

        if not records.exists():
            raise serializers.ValidationError("Invalid OTP.")

        record = records.first()

        if record.is_verified:
            raise serializers.ValidationError("OTP has already been used.")

        if record.is_expired():
            raise serializers.ValidationError("OTP has expired.")

        self.record = record
        return data



    def create(self, validated_data):
        self.record.is_verified = True
        self.record.save()
    
        from admin_part.models import CustomUser
        user = CustomUser.objects.get(email__iexact=validated_data['email'])
    
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
    
        # Extracting employee_id and level from related EmailCenter
        employee_id = user.level_id.employee_id if user.level_id else None
        user_level = user.level_id.level if user.level_id else None
    
        return {
            "message": "OTP verified successfully",
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "employee_id": employee_id,
            "user_level": user_level,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }

class UserProfileBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['phone_number', 'bio', 'profile_picture']

    def validate(self, data):
        # Convert empty strings to None
        for field in ['phone_number', 'bio']:
            if field in data and data[field] == '':
                data[field] = None
        return data


# Serializer for API responses including user info
class UserProfileDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='user.get_full_name')
    email = serializers.EmailField(source='user.email')
    profile_picture_url = serializers.SerializerMethodField()
    employee_id = serializers.CharField(source='user.level_id.employee_id', read_only=True)

    class Meta:
        model = UserProfile
        fields = [
            'full_name',
            'email',
            'employee_id',  # ✅ added
            'phone_number',
            'bio',
            'profile_picture_url',
        ]

    def get_profile_picture_url(self, obj):
        request = self.context.get('request')
        if obj.profile_picture and hasattr(obj.profile_picture, 'url'):
            return request.build_absolute_uri(obj.profile_picture.url)
        return None

    
class UserProfileUpdateSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="user.full_name", required=False)
    email = serializers.EmailField(source="user.email", read_only=True)  # just for display, not editable

    class Meta:
        model = UserProfile
        fields = ["email", "full_name", "phone_number", "bio", "profile_picture"]

    def update(self, instance, validated_data):
        # ✅ Update user fields (CustomUser)
        user_data = validated_data.pop("user", {})
        if "full_name" in user_data:
            instance.user.full_name = user_data["full_name"]
            instance.user.save()

        # ✅ Update profile fields (UserProfile)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        return instance
    
class UserDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserDevice
        fields = ["device_token"]
        extra_kwargs = {
            "device_token": {"validators": []}  # disables unique validation
        }


# phone OTP
# -------- Send OTP -------- #
class SendPhoneOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)

    def validate_phone_number(self, value):
        if not value or not value.replace('+', '').isdigit():
            raise serializers.ValidationError("Invalid phone number format.")

        # Check if user exists
        if not CustomUser.objects.filter(phone_number=value).exists():
            raise serializers.ValidationError("User not found. Please register first.")
        return value

    def create(self, validated_data):
        phone_number = validated_data['phone_number']
        otp = generate_otp()

        PhoneOTP.objects.update_or_create(
            phone_number=phone_number,
            defaults={'otp': otp, 'is_verified': False, 'created_at': timezone.now()}
        )

        send_otp(phone_number, otp)
        return {'phone_number': phone_number, 'otp_sent': True}


# -------- Verify OTP -------- #
class VerifyPhoneOTPSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=15)
    otp = serializers.CharField(max_length=6)

    def validate(self, data):
        phone_number = data.get('phone_number')
        otp = data.get('otp')

        # Verify existing user
        try:
            user = CustomUser.objects.get(phone_number=phone_number)
        except CustomUser.DoesNotExist:
            raise serializers.ValidationError("User not found. Please register first.")

        # Verify OTP record
        try:
            otp_record = PhoneOTP.objects.get(phone_number=phone_number, otp=otp)
        except PhoneOTP.DoesNotExist:
            raise serializers.ValidationError("Invalid OTP or phone number.")

        if otp_record.is_expired():
            raise serializers.ValidationError("OTP has expired.")

        data['user'] = user
        data['otp_record'] = otp_record
        return data

    def create(self, validated_data):
        otp_record = validated_data['otp_record']
        user = validated_data['user']

        otp_record.is_verified = True
        otp_record.save()

        return {'user': user, 'message': 'OTP verified successfully'}