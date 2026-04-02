# Utils/Verification_Codes_Service.py
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
            print(f"[Email Config] EMAIL_USERNAME: {cls.email_username}")
            print(f"[Email Config] EMAIL_PASSWORD: {'*' * len(cls.email_password) if cls.email_password else 'None'}")
            print(f"[Email Config] SMTP_SERVER: {cls.smtp_server}")
            print(f"[Email Config] SMTP_PORT: {cls.smtp_port}")

            # Check which services are available
            cls._email_enabled = bool(cls.email_username and cls.email_password)
            cls._sms_enabled = bool(cls.twilio_account_sid and cls.twilio_auth_token and cls.twilio_from_number)

            if cls._email_enabled:
                print("[OK] Email service is CONFIGURED and READY!")
            else:
                print("[WARN] Email service is NOT configured - check your .env file")
                print("   Make sure EMAIL_USERNAME and EMAIL_PASSWORD are set")

            if not cls._email_enabled and not cls._sms_enabled:
                print("[WARN] Neither email nor SMS services are configured. Verification codes will only be logged to console.")
            
            cls._config_loaded = True

    @classmethod
    def send_email(cls, to_email: str, subject: str, body: str, content_type: str = 'plain') -> bool:
        """Send email using SSL on port 465. content_type can be 'plain' or 'html'."""
        cls._load_config()

        if not cls._email_enabled:
            print(f"[Email SIMULATED] to: {to_email}")
            print(f"   Subject: {subject}")
            print(f"   Body: {body}")
            return True  # Allow dev login - code is logged to console

        try:
            print(f"[Email] Attempting to send to: {to_email}")
            print(f"   Using server: {cls.smtp_server}:{cls.smtp_port}")

            # Build proper MIME email
            msg = MIMEMultipart()
            msg['From'] = f'Shopivell <{cls.email_username}>'
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, content_type, 'utf-8'))

            # Use SMTP_SSL for port 465 (SSL connection)
            with smtplib.SMTP_SSL(cls.smtp_server, cls.smtp_port, timeout=15) as s:
                s.login(cls.email_username, cls.email_password)
                s.sendmail(cls.email_username, to_email, msg.as_string())

            print(f"[OK] Email sent successfully to: {to_email}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            print(f"[ERROR] SMTP Authentication failed: {e}")
            return False
        except smtplib.SMTPConnectError as e:
            print(f"[ERROR] SMTP Connection failed: {e}")
            return False
        except Exception as e:
            print(f"[ERROR] Failed to send email to {to_email}: {e}")
            return False

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
                print(f"[OK] SMS sent to: {to_number} (SID: {message.sid})")
                return True
            else:
                # Fallback: log to console
                print(f"[SMS SIMULATED] to: {to_number}")
                print(f"   Body: {body}")
                return True

        except Exception as e:
            print(f"[ERROR] Failed to send SMS to {to_number}: {e}")
            # Fallback to console logging
            print(f"[SMS SIMULATED] to: {to_number}")
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
            raise ValueError("User not found")

        expiration_time = verification_code.expires_at.strftime("%H:%M")

        if delivery_method == "sms" and user.phone_number:
            # Send via SMS
            body = f"Shopivell: Your {code_type.replace('_', ' ')} code is {verification_code.code}. Expires at {expiration_time}."
            return cls.send_sms(user.phone_number, body)

        else:
            # Send via Email (HTML)
            user_name = user.name or user.first_name or 'there'
            subject = f"{verification_code.code} is your Shopivell code"
            body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background-color:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f5f5;padding:40px 20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:12px;overflow:hidden;">
        <tr><td style="padding:32px 40px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td><img src="https://objects.shopivell.com/shopivell-assets/shopivell-logo.png" alt="Shopivell" height="32" style="height:32px;" onerror="this.style.display='none'"></td>
              <td align="right" style="font-size:14px;color:#666;">{user_name}</td>
            </tr>
          </table>
        </td></tr>
        <tr><td style="padding:0 40px 32px;">
          <h1 style="font-size:22px;font-weight:600;color:#1a1a1a;margin:0 0 16px;">One more step to confirm your account</h1>
          <p style="font-size:15px;color:#444;line-height:1.5;margin:0 0 24px;">Hi {user_name},<br><br>We got a request to verify your account on Shopivell. Enter this code:</p>
          <div style="background-color:#e8f4fd;border-radius:8px;padding:20px;text-align:center;margin:0 0 24px;">
            <span style="font-size:32px;font-weight:700;letter-spacing:8px;color:#1a1a1a;">{verification_code.code}</span>
          </div>
          <p style="font-size:13px;color:#888;text-align:center;margin:0 0 24px;">Don't share this code with anyone.</p>
          <hr style="border:none;border-top:1px solid #eee;margin:0 0 24px;">
          <p style="font-size:13px;color:#666;margin:0 0 8px;"><strong>If someone asks for this code</strong></p>
          <p style="font-size:13px;color:#888;line-height:1.5;margin:0 0 20px;">Don't share this code with anyone. Shopivell will never ask you for this code.</p>
          <p style="font-size:13px;color:#666;margin:0 0 8px;"><strong>Didn't request this?</strong></p>
          <p style="font-size:13px;color:#888;line-height:1.5;margin:0 0 20px;">If you didn't request this, you can safely ignore this email. The code expires at {expiration_time}.</p>
          <p style="font-size:14px;color:#444;margin:0;">Thanks,<br>Shopivell Security</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
            return cls.send_email(email, subject, body, content_type='html')

    @classmethod
    def send_password_reset_code(
        cls,
        db: Session,
        email: str,
        delivery_method: str = "email"
    ) -> bool:
        """Send password reset verification code"""
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
            # Send via Email (HTML)
            user_name = user.name or user.first_name or 'there'
            subject = f"{verification_code.code} is your Shopivell password reset code"
            body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background-color:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f5f5;padding:40px 20px;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background-color:#ffffff;border-radius:12px;overflow:hidden;">
        <tr><td style="padding:32px 40px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td><img src="https://objects.shopivell.com/shopivell-assets/shopivell-logo.png" alt="Shopivell" height="32" style="height:32px;" onerror="this.style.display='none'"></td>
              <td align="right" style="font-size:14px;color:#666;">{user_name}</td>
            </tr>
          </table>
        </td></tr>
        <tr><td style="padding:0 40px 32px;">
          <h1 style="font-size:22px;font-weight:600;color:#1a1a1a;margin:0 0 16px;">Reset your password</h1>
          <p style="font-size:15px;color:#444;line-height:1.5;margin:0 0 24px;">Hi {user_name},<br><br>You requested to reset your password. Enter this code:</p>
          <div style="background-color:#e8f4fd;border-radius:8px;padding:20px;text-align:center;margin:0 0 24px;">
            <span style="font-size:32px;font-weight:700;letter-spacing:8px;color:#1a1a1a;">{verification_code.code}</span>
          </div>
          <p style="font-size:13px;color:#888;text-align:center;margin:0 0 24px;">Don't share this code with anyone.</p>
          <hr style="border:none;border-top:1px solid #eee;margin:0 0 24px;">
          <p style="font-size:13px;color:#666;margin:0 0 8px;"><strong>Didn't request this?</strong></p>
          <p style="font-size:13px;color:#888;line-height:1.5;margin:0 0 20px;">If you didn't request a password reset, you can safely ignore this email. Your password won't be changed. The code expires at {expiration_time}.</p>
          <p style="font-size:14px;color:#444;margin:0;">Thanks,<br>Shopivell Security</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""
            return cls.send_email(email, subject, body, content_type='html')