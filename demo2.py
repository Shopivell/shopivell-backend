import time
from paynow import Paynow
INTEGRATION_ID = "22701"
INTEGRATION_KEY = "34f9dddf-4012-4556-a7c6-5a32f0f537ca"

paynow = Paynow(
    INTEGRATION_ID, 
    INTEGRATION_KEY,
    'http://google.com', 
    'http://google.com'
    )

# FIX: Add your verified merchant email address back into the create_payment call
# Replace 'your_verified_email@example.com' with the exact email Paynow has on file.
payment = paynow.create_payment('Order', 'farairhato@gmail.com') 

payment.add('Payment for stuff', 1)

# Ensure you use a test mobile number like '0771111111'
response = paynow.send_mobile(payment, '0771111111', 'ecocash')
print("Response: ", response.status)

if(response.success):
    poll_url = response.poll_url

    print("Poll Url: ", poll_url)

    status = paynow.check_transaction_status(poll_url)

    time.sleep(30)

    print("Payment Status: ", status.status)
else:
    # Handle the error case gracefully
    print("Error:", response.errors)
