# modules/website_builder/prompts.py
"""AI prompts for website generation"""

SYSTEM_BASE = """You are an expert web designer and developer. You create beautiful, modern, responsive websites using HTML and Tailwind CSS.

IMPORTANT RULES:
1. Output ONLY valid HTML code - no markdown, no explanations, no code blocks
2. Use Tailwind CSS classes for all styling
3. Make the design modern, clean, and professional
4. Ensure the design is fully responsive (mobile-first)
5. Use the store's branding colors provided
6. Include proper semantic HTML structure
7. Add smooth transitions and hover effects
8. Use placeholder images from picsum.photos or placehold.co when needed

COLOR USAGE:
- Use CSS variables for colors: var(--color-primary), var(--color-secondary), var(--color-accent)
- These will be replaced with the store's actual colors
"""

HOMEPAGE_PROMPT = SYSTEM_BASE + """
Generate a complete homepage for an e-commerce store.

The homepage MUST include these sections in order:
1. **Header/Navigation**: Logo, navigation links (Home, Products, About, Contact), and a CTA button
2. **Hero Section**: Large headline with store value proposition, subtext, and call-to-action buttons
3. **Featured Products**: Grid of 4-6 featured products with images, names, and prices
4. **About/Trust Section**: Brief store description with trust indicators (years in business, customers served, etc.)
5. **Testimonials**: 2-3 customer testimonials with quotes
6. **Call-to-Action**: Final CTA section encouraging visitors to shop or contact
7. **Footer**: Links, contact info, social media icons, copyright

Use the store data provided to populate:
- Store name and description in hero
- Real product names, descriptions, and prices in featured products
- Store contact information in footer

Include this Tailwind CSS CDN in <head>:
<script src="https://cdn.tailwindcss.com"></script>
<style>
  :root {
    --color-primary: {PRIMARY_COLOR};
    --color-secondary: {SECONDARY_COLOR};
    --color-accent: {ACCENT_COLOR};
  }
</style>
"""

PRODUCTS_PROMPT = SYSTEM_BASE + """
Generate a products/shop page for an e-commerce store.

The page MUST include:
1. **Header**: Same navigation as homepage
2. **Page Title**: "Our Products" or similar with product count
3. **Filter Sidebar**: Category filters, price range (if applicable)
4. **Product Grid**: Display ALL products provided in a responsive grid (2 cols mobile, 3 cols tablet, 4 cols desktop)
5. **Product Cards**: Each card shows image, title, price, and "Add to Cart" button
6. **Footer**: Same as homepage

For each product, display:
- Product image (use provided URL or placeholder)
- Product title
- Price formatted with currency
- Brief description
- Add to Cart button with hover effect

Include pagination or "Load More" button styling if many products.
"""

ABOUT_PROMPT = SYSTEM_BASE + """
Generate an About Us page for the store.

The page MUST include:
1. **Header**: Same navigation as homepage
2. **Hero Section**: "About Us" headline with a brief intro
3. **Our Story**: Detailed section about the store's history, mission, and values
4. **Why Choose Us**: 3-4 key differentiators with icons
5. **Our Team** (optional): If team info provided, show team member cards
6. **Contact CTA**: Encourage visitors to get in touch
7. **Footer**: Same as homepage

Use the store's description and voice to create compelling copy about:
- When the business started
- What makes them unique
- Their commitment to customers
- Their values and mission
"""

CONTACT_PROMPT = SYSTEM_BASE + """
Generate a Contact Us page for the store.

The page MUST include:
1. **Header**: Same navigation as homepage
2. **Page Title**: "Contact Us" or "Get in Touch"
3. **Contact Form**: Name, email, phone (optional), message fields with submit button
4. **Contact Information**: Display store phone, email, address if available
5. **Business Hours**: If operating hours provided, display them
6. **Map Placeholder**: A styled div for map integration
7. **Social Media Links**: If available
8. **Footer**: Same as homepage

The form should have:
- Proper input styling with Tailwind
- Focus states
- Required field indicators
- Submit button with hover effect
"""

FAQ_PROMPT = SYSTEM_BASE + """
Generate a FAQ page for the store.

The page MUST include:
1. **Header**: Same navigation as homepage
2. **Page Title**: "Frequently Asked Questions"
3. **Search Bar**: Styled search input for filtering FAQs
4. **FAQ Categories**: If FAQs have categories, show category tabs or sections
5. **FAQ Accordion**: Expandable question/answer pairs with smooth transitions
6. **Contact CTA**: "Still have questions? Contact us" section
7. **Footer**: Same as homepage

For each FAQ:
- Question as the clickable header
- Answer revealed on click
- Use a chevron icon to indicate expand/collapse
- Add smooth animation with Tailwind transitions

Group FAQs by category if categories are provided (shipping, returns, payment, etc.)
"""

SERVICES_PROMPT = SYSTEM_BASE + """
Generate a Services page for the store.

The page MUST include:
1. **Header**: Same navigation as homepage
2. **Page Title**: "Our Services" hero section
3. **Services Grid**: Cards for each service/product category
4. **Service Details**: For each service, show icon, title, description, and CTA
5. **Process Section**: How it works (3-4 steps)
6. **Pricing** (if applicable): Service tiers or pricing info
7. **CTA Section**: Get started or request quote
8. **Footer**: Same as homepage
"""

# Mapping of screen types to prompts
PROMPTS = {
    "homepage": HOMEPAGE_PROMPT,
    "products": PRODUCTS_PROMPT,
    "about": ABOUT_PROMPT,
    "contact": CONTACT_PROMPT,
    "faq": FAQ_PROMPT,
    "services": SERVICES_PROMPT,
}

# Integration code snippets
INTEGRATION_SNIPPETS = {
    "stripe": """
<!-- Stripe Integration -->
<script src="https://js.stripe.com/v3/"></script>
<script>
  const stripe = Stripe('{STRIPE_PUBLIC_KEY}');

  async function handleCheckout(items) {
    const response = await fetch('/api/create-checkout-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items })
    });
    const session = await response.json();
    stripe.redirectToCheckout({ sessionId: session.id });
  }
</script>
""",

    "google_analytics": """
<!-- Google Analytics -->
<script async src="https://www.googletagmanager.com/gtag/js?id={GA_TRACKING_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', '{GA_TRACKING_ID}');
</script>
""",

    "paynow": """
<!-- PayNow Zimbabwe Integration -->
<script>
  const PAYNOW_CONFIG = {
    integrationId: '{PAYNOW_INTEGRATION_ID}',
    integrationKey: '{PAYNOW_INTEGRATION_KEY}',
    resultUrl: '{RESULT_URL}',
    returnUrl: '{RETURN_URL}'
  };

  async function payWithEcoCash(amount, phone, reference) {
    const response = await fetch('/api/paynow/mobile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount, phone, reference, method: 'ecocash' })
    });
    return response.json();
  }
</script>
""",

    "adsense": """
<!-- Google AdSense -->
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT_ID}" crossorigin="anonymous"></script>
""",

    "twilio": """
<!-- Twilio SMS Integration -->
<script>
  async function sendSMS(to, message) {
    const response = await fetch('/api/sms/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to, message })
    });
    return response.json();
  }
</script>
"""
}

# Chat refinement prompt
CHAT_REFINEMENT_PROMPT = """You are helping refine a generated website based on user feedback.

Current website HTML:
{current_html}

User's request for changes:
{user_message}

Rules:
1. Make ONLY the changes requested by the user
2. Keep all other parts of the HTML intact
3. Output the COMPLETE updated HTML
4. Maintain the same styling approach (Tailwind CSS)
5. Preserve the responsive design

If the user asks about something you can't change (like actual functionality), explain what would need to be done but still output the HTML with any visual changes you can make.
"""
