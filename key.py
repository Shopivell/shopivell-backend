# import secrets
# secret_key = secrets.token_hex(32)  # Generates a 64-character hexadecimal string
# print(secret_key)

import jwt

SECRET_KEY = "4a593346871ae60e9ebd4e79ed90b8da539aeead09972ae0c4d08ec523951835"

token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkMzg2YzhhZC04ODlkLTQwMTMtOWRmZi00YjNhZTMzMWY2NDQiLCJkZXZpY2VfaWQiOiI2ZTBhYzU3YS1lMTZiLTQyZDEtYmI5OS0wYTAyNDI4YzRkYWEifQ.vjVEYGmEX06N6_QTklyTATdC39IdfiFQP58Rp56cYg4"

payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
print(payload)

