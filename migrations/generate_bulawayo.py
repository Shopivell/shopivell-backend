import pandas as pd

# Read the Excel file
df = pd.read_excel(r'C:\Users\user\Downloads\STOCK TOTAL BYO 14102026.xlsx', header=6)
df = df[df['DESCR'].notna() & (df['DESCR'].str.strip() != '')]

# Generate Python code for products
with open(r'C:\Users\user\Desktop\projects\shopivell-backend\migrations\bulawayo_products_data.py', 'w', encoding='utf-8') as f:
    f.write('PRODUCTS = [\n')
    for i, row in df.iterrows():
        name = str(row['DESCR']).strip()
        # Escape backslashes and quotes for Python string
        name = name.replace('\\', '\\\\').replace('"', '\\"')
        price = row.get('RETAIL', 0)
        if pd.isna(price):
            price = 0
        f.write(f'    ("{name}", {float(price):.2f}),\n')
    f.write(']\n')

print(f"Generated {len(df)} products")
