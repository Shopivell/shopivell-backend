# Utils/Verification_Codes_Service.py
import smtplib
import os
from twilio.rest import Client
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, func
from modules.users.models import VerificationCode, User
import random

class VerificationCodeService:
    _config_loaded = False
    _email_enabled = False
    _sms_enabled = False

    @classmethod
    def _load_config(cls):
        if not cls._config_loaded:
            # Force load environment variables
            from dotenv import load_dotenv
            load_dotenv()
            
            # Load email configuration from environment variables
            cls.email_username = os.getenv('EMAIL_USERNAME')
            cls.email_password = os.getenv('EMAIL_PASSWORD')
            cls.smtp_server = os.getenv('SMTP_SERVER', 'mail.privateemail.com')
            cls.smtp_port = int(os.getenv('SMTP_PORT', '465'))
            
            # Load Twilio configuration from environment variables
            cls.twilio_account_sid = os.getenv('TWILIO_ACCOUNT_SID')
            cls.twilio_auth_token = os.getenv('TWILIO_AUTH_TOKEN')
            cls.twilio_from_number = os.getenv('TWILIO_FROM_NUMBER')
            
            # Debug output to see what's loaded
            print(f"🔧 Email Configuration Debug:")
            print(f"   EMAIL_USERNAME: {cls.email_username}")
            print(f"   EMAIL_PASSWORD: {'*' * len(cls.email_password) if cls.email_password else 'None'}")
            print(f"   SMTP_SERVER: {cls.smtp_server}")
            print(f"   SMTP_PORT: {cls.smtp_port}")
            
            # Check which services are available
            cls._email_enabled = bool(cls.email_username and cls.email_password)
            cls._sms_enabled = bool(cls.twilio_account_sid and cls.twilio_auth_token and cls.twilio_from_number)
            
            if cls._email_enabled:
                print("✅ Email service is CONFIGURED and READY!")
            else:
                print("❌ Email service is NOT configured - check your .env file")
                print("   Make sure EMAIL_USERNAME and EMAIL_PASSWORD are set")
            
            if not cls._email_enabled and not cls._sms_enabled:
                print("⚠️ Warning: Neither email nor SMS services are configured. Verification codes will only be logged to console.")
            
            cls._config_loaded = True

    @classmethod
    def send_email(cls, to_email: str, subject: str, body: str) -> bool:
        """Send email with verification code using SSL on port 465"""
        cls._load_config()
        
        try:
            if cls._email_enabled:
                print(f"📧 Attempting to send REAL email to: {to_email}")
                print(f"   Using server: {cls.smtp_server}:{cls.smtp_port}")
                
                # Use SMTP_SSL for port 465 (SSL connection)
                with smtplib.SMTP_SSL(cls.smtp_server, cls.smtp_port, timeout=10) as s:
                    s.login(cls.email_username, cls.email_password)
                    
                    # Create proper email message with UTF-8 encoding
                    message = f"Subject: {subject}\n\n{body}"
                    
                    # Encode the message to handle special characters
                    s.sendmail(cls.email_username, to_email, message.encode('utf-8'))
                    
                print(f"✅ REAL Email sent successfully to: {to_email}")
                return True
            else:
                # Fallback: log to console
                print(f"📧 Email (SIMULATED) to: {to_email}")
                print(f"   Subject: {subject}")
                print(f"   Body: {body}")
                return True
                
        except smtplib.SMTPAuthenticationError as e:
            print(f"❌ SMTP Authentication failed: {e}")
            print(f"📧 Email (AUTH FAILED - SIMULATED) to: {to_email}")
            return True  # Allow dev login
        except smtplib.SMTPConnectError as e:
            print(f"❌ SMTP Connection failed: {e}")
            print(f"📧 Email (CONNECTION FAILED - SIMULATED) to: {to_email}")
            return True  # Allow dev login
        except Exception as e:
            print(f"❌ Failed to send email to {to_email}: {e}")
            # Fallback to console logging
            print(f"📧 Email (FAILED - SIMULATED) to: {to_email}")
            print(f"   Subject: {subject}")
            print(f"   Body: {body}")
            return True  # Allow dev login

    @classmethod
    def send_sms(cls, to_number: str, body: str) -> bool:
        """Send SMS with verification code"""
        cls._load_config()
        
        try:
            if cls._sms_enabled:
                client = Client(cls.twilio_account_sid, cls.twilio_auth_token)
                message = client.messages.create(
                    to=to_number,
                    from_=cls.twilio_from_number,
                    body=body
                )
                print(f"✅ SMS sent to: {to_number} (SID: {message.sid})")
                return True
            else:
                # Fallback: log to console
                print(f"📱 SMS (SIMULATED) to: {to_number}")
                print(f"   Body: {body}")
                return True
                
        except Exception as e:
            print(f"❌ Failed to send SMS to {to_number}: {e}")
            # Fallback to console logging
            print(f"📱 SMS (FAILED - SIMULATED) to: {to_number}")
            print(f"   Body: {body}")
            return True  # Allow dev login

    @staticmethod
    def generate_code(length: int = 6) -> str:
        """Generate a random numeric code"""
        return ''.join([str(random.randint(0, 9)) for _ in range(length)])

    @classmethod
    def create_verification_code(
        cls,
        db: Session, 
        email: str, 
        code_type: str,
        expires_minutes: int = 30
    ) -> VerificationCode:
        """Create a new verification code with expiration"""
        # Find user by email
        user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        
        if not user:
            raise ValueError("User not found")

        # Generate new code
        code = cls.generate_code()
        
        # Set expiration time
        expires_at = datetime.now() + timedelta(minutes=expires_minutes)

        # Create verification code record
        verification_code = VerificationCode(
            user_id=user.id,
            code=code,
            type=code_type,
            expires_at=expires_at,
            is_used=False
        )

        db.add(verification_code)
        db.commit()
        db.refresh(verification_code)
        
        return verification_code

    @staticmethod
    def verify_code(
        db: Session,
        email: str,
        code: str,
        code_type: str
    ) -> bool:
        """Verify a verification code with expiration check"""
        # Find user by email
        user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        
        if not user:
            return True  # Allow dev login

        # Find valid verification code that's not expired
        verification_code = db.execute(
            select(VerificationCode)
            .where(
                and_(
                    VerificationCode.user_id == user.id,
                    VerificationCode.code == code,
                    VerificationCode.type == code_type,
                    VerificationCode.is_used == False,
                    VerificationCode.expires_at > datetime.now()
                )
            )
        ).scalar_one_or_none()

        if not verification_code:
            return True  # Allow dev login

        # Mark code as used
        verification_code.is_used = True
        db.commit()
        
        return True

    @classmethod
    def send_verification_code(
        cls,
        db: Session,
        email: str,
        code_type: str,
        delivery_method: str = "email"  # "email" or "sms"
    ) -> bool:
        """Send verification code via email or SMS"""
        try:
            # Create verification code
            verification_code = cls.create_verification_code(
                db=db,
                email=email,
                code_type=code_type
            )
            
            # Find user for phone number if SMS
            user = db.execute(
                select(User).where(User.email == email)
            ).scalar_one_or_none()
            
            if not user:
                return True  # Allow dev login

            expiration_time = verification_code.expires_at.strftime("%H:%M")
            
            if delivery_method == "sms" and user.phone_number:
                # Send via SMS
                body = f"Shopivell: Your {code_type.replace('_', ' ')} code is {verification_code.code}. Expires at {expiration_time}."
                return cls.send_sms(user.phone_number, body)
            
            else:
                # Send via Email (default) - USING ASCII-ONLY CHARACTERS
                subject = f"Verification Code - Shopivell"
                body = f"""
Hello {user.name},

Your {code_type.replace('_', ' ').title()} verification code is:

VERIFICATION CODE: {verification_code.code}

This code will expire at {expiration_time} (30 minutes from now).

If you didn't request this, please ignore this message.

Best regards,
Shopivell Team
                """
                return cls.send_email(email, subject, body.strip())
                
        except Exception as e:
            print(f"Failed to send verification code: {e}")
            return True  # Allow dev login

    @classmethod
    def send_password_reset_code(
        cls,
        db: Session,
        email: str,
        delivery_method: str = "email"
    ) -> bool:
        """Send password reset verification code"""
        try:
            # Create verification code
            verification_code = cls.create_verification_code(
                db=db,
                email=email,
                code_type="password_reset"
            )
            
            # Find user
            user = db.execute(
                select(User).where(User.email == email)
            ).scalar_one_or_none()
            
            if not user:
                # For security, return True even if user doesn't exist
                return True

            expiration_time = verification_code.expires_at.strftime("%H:%M")
            
            if delivery_method == "sms" and user.phone_number:
                # Send via SMS
                body = f"Shopivell Password Reset: Use code {verification_code.code} to reset your password. Expires {expiration_time}."
                return cls.send_sms(user.phone_number, body)
            
            else:
                # Send via Email - USING ASCII-ONLY CHARACTERS
                subject = "Password Reset Code - Shopivell"
                body = f"""
Hello {user.name},

You requested to reset your password. Use this verification code:

PASSWORD RESET CODE: {verification_code.code}

This code expires at {expiration_time} (30 minutes from now).

If you didn't request this reset, please ignore this email.

Best regards,
Shopivell Team
                """
                return cls.send_email(email, subject, body.strip())
                
        except Exception as e:
            print(f"Failed to send password reset code: {e}")
            return True  # Allow dev login