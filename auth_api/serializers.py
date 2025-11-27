from rest_framework import serializers
from django.utils import timezone
from admin_part.models import CustomUser, EmailCenter
from .utils import generate_otp, send_otp_via_email
from .models import EmailOTP,UserDevice
from admin_part.models import UserProfile
from .models import *
from .utils import send_otp
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class UserRegistrationSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(write_only=True)
    phone_number = serializers.CharField(max_length=15, required=True)
    email = serializers.EmailField(required=True)  # Changed to required=True

    class Meta:
        model = CustomUser
        fields = ['full_name', 'email', 'dob', 'phone_number', 'password', 'confirm_password']
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def validate(self, attrs):
        email = attrs.get('email')
        phone_number = attrs.get('phone_number')
        dob = attrs.get('dob')
        password = attrs.get('password')
        confirm_password = attrs.get('confirm_password')

        # ✅ 1. Ensure ALL THREE fields are provided
        if not phone_number:
            raise serializers.ValidationError({
                "phone_number": "Phone number is required for registration."
            })
        
        if not email:
            raise serializers.ValidationError({
                "email": "Email is required for registration."
            })
            
        if not dob:
            raise serializers.ValidationError({
                "dob": "Date of birth is required for registration."
            })

        # ✅ 2. Find EXACT match in EmailCenter (all three fields must match)
        try:
            email_center = EmailCenter.objects.get(
                phone_number=phone_number,
                email=email,
                dob=dob
            )
        except EmailCenter.DoesNotExist:
            raise serializers.ValidationError({
                "detail": "Provided phone number, email, and date of birth do not match any authorized record in our system."
            })
        except EmailCenter.MultipleObjectsReturned:
            # If multiple records found, still use the first one
            email_center = EmailCenter.objects.filter(
                phone_number=phone_number,
                email=email,
                dob=dob
            ).first()

        # ✅ 3. Check if the EmailCenter record is suspended
        if email_center.is_suspended:
            if email_center.suspension_until and email_center.suspension_until > timezone.now():
                raise serializers.ValidationError({
                    "detail": f"Your account is suspended until {email_center.suspension_until}. Please contact administrator."
                })
            elif email_center.suspension_until is None:
                raise serializers.ValidationError({
                    "detail": "Your account is suspended indefinitely. Please contact administrator."
                })

        # ✅ 4. Check if phone number already used in CustomUser
        if CustomUser.objects.filter(phone_number=phone_number).exists():
            raise serializers.ValidationError({
                "phone_number": "This phone number is already registered."
            })

        # ✅ 5. Check if email already used in CustomUser
        if CustomUser.objects.filter(email=email).exists():
            raise serializers.ValidationError({
                "email": "This email is already registered."
            })

        # ✅ 6. Confirm password match
        if password != confirm_password:
            raise serializers.ValidationError({
                "confirm_password": "Passwords do not match."
            })

        # ✅ 7. Store matched EmailCenter for use in create()
        attrs['email_center'] = email_center
        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        email_center = validated_data.pop('email_center', None)
        validated_data['level_id'] = email_center
        user = CustomUser.objects.create_user(**validated_data)
        return user

class CustomLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    phone_number = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email')
        phone_number = attrs.get('phone_number')
        password = attrs.get('password')

        if not password or (not email and not phone_number):
            raise serializers.ValidationError("Email or phone number and password are required.")

        # Find user
        if email:
            user = CustomUser.objects.filter(email__iexact=email).first()
        elif phone_number:
            user = CustomUser.objects.filter(phone_number=phone_number).first()
        else:
            user = None

        if not user or not user.check_password(password):
            raise serializers.ValidationError("Invalid credentials.")

        if not user.is_active:
            raise serializers.ValidationError("This account is inactive.")

        attrs['user'] = user
        return attrs

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

        records = EmailOTP.objects.filter(
            email__iexact=email,
            otp=otp
        ).order_by('-created_at')

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
        # Mark OTP as used
        self.record.is_verified = True
        self.record.save()

        from admin_part.models import CustomUser
        user = CustomUser.objects.get(email__iexact=validated_data['email'])

        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)

        # Extract related EmailCenter fields
        employee_id = user.level_id.employee_id if user.level_id else None
        user_level = user.level_id.level if user.level_id else None

        # 🔥 Added the same properties you added in login API
        return {
            "message": "OTP verified successfully",
            "user_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "employee_id": employee_id,
            "user_level": user_level,

            # 🔥 Added Permission Properties
            "can_add_story": user.can_add_story,
            "can_upload_feed": user.can_upload_feed,
            "can_share_media": user.can_share_media,
            "can_access_web_app": user.can_access_web_app,
            "is_suspended": user.is_suspended,

            # Tokens
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }


class UserProfileBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ['bio', 'profile_picture']  # Removed phone_number

    def validate(self, data):
        # Convert empty strings to None
        for field in ['bio']:
            if field in data and data[field] == '':
                data[field] = None
        return data

# Serializer for API responses including user info
class UserProfileDetailSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    phone_number = serializers.CharField(source='user.phone_number', read_only=True)  # fetch from CustomUser
    employee_id = serializers.CharField(source='user.level_id.employee_id', read_only=True)
    profile_picture_url = serializers.SerializerMethodField()
    can_access_web_app = serializers.SerializerMethodField()  

    class Meta:
        model = UserProfile
        fields = [
            'full_name',
            'email',
            'employee_id',
            'phone_number',  # ✅ now fetched from CustomUser
            'bio',
            'profile_picture_url',
            'can_access_web_app'
        ]
    def get_can_access_web_app(self, obj):
        return obj.user.can_access_web_app

    def get_profile_picture_url(self, obj):
        request = self.context.get('request')
        if obj.profile_picture and hasattr(obj.profile_picture, 'url'):
            return request.build_absolute_uri(obj.profile_picture.url)
        return None

class UserProfileUpdateSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="user.full_name", required=False)
    email = serializers.EmailField(source="user.email", read_only=True)  # just for display, not editable
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)  # display only

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

    MASTER_OTP = "999999"  # <-- Master OTP

    def validate(self, data):
        phone_number = data.get('phone_number')
        otp = data.get('otp')

        # Verify existing user
        try:
            user = CustomUser.objects.get(phone_number=phone_number)
        except CustomUser.DoesNotExist:
            raise serializers.ValidationError("User not found. Please register first.")

        data['user'] = user  # Always add user

        # If master OTP is entered, bypass normal OTP check
        if otp == self.MASTER_OTP:
            data['otp_record'] = None  # No OTP record needed
            return data

        # Normal OTP verification
        try:
            otp_record = PhoneOTP.objects.get(phone_number=phone_number, otp=otp)
        except PhoneOTP.DoesNotExist:
            raise serializers.ValidationError("Invalid OTP or phone number.")

        if otp_record.is_expired():
            raise serializers.ValidationError("OTP has expired.")

        data['otp_record'] = otp_record
        return data

    def create(self, validated_data):
        otp_record = validated_data.get('otp_record')
        user = validated_data['user']

        # If normal OTP was used, mark it verified
        if otp_record:
            otp_record.is_verified = True
            otp_record.save()

        return {'user': user, 'message': 'OTP verified successfully'}
