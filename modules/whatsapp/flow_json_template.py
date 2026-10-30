"""
WhatsApp Flow JSON Template for ordering.

Defines the screen structure (layout + components).
Actual data (product lists, prices) is injected at runtime
via the data endpoint responses.
"""


def generate_flow_json() -> dict:
    """
    Generate the WhatsApp Flow JSON for an ordering flow.

    Screens:
      PRODUCT_BROWSE  → pick a product
      PRODUCT_DETAIL  → see details, choose quantity
      CART_REVIEW     → review cart, add more or checkout
      DELIVERY_INFO   → delivery method + address
      PAYMENT_METHOD  → payment choice + EcoCash number
      ORDER_SUMMARY   → confirm and place order
    """
    return {
        "version": "6.0",
        "data_api_version": "3.0",
        "routing_model": {},
        "screens": [
            _product_browse_screen(),
            _product_detail_screen(),
            _cart_review_screen(),
            _delivery_info_screen(),
            _payment_method_screen(),
            _order_summary_screen(),
        ],
    }


def _delivery_address_screen() -> dict:
    """Standalone address form used by the conversational checkout flow."""
    fields = [("street", "Street and house number"), ("suburb", "Suburb or area"), ("city", "City")]
    children = [{"type": "TextHeading", "text": "Delivery address"}]
    children += [{"type": "TextInput", "name": key, "label": label, "required": True,
                  "input-type": "text"} for key, label in fields]
    children.append({"type": "Footer", "label": "Save address", "on-click-action": {
        "name": "complete", "payload": {"form_type": "delivery_address",
        "street": "${form.street}", "suburb": "${form.suburb}", "city": "${form.city}"}}})
    return {"id": "DELIVERY_ADDRESS", "title": "Delivery address", "terminal": True,
            "layout": {"type": "SingleColumnLayout", "children": [
                {"type": "Form", "name": "address_form", "children": children}]}}


def generate_delivery_address_flow_json() -> dict:
    """A standalone terminal Flow; its completion only updates checkout state."""
    return {"version": "6.0", "screens": [_delivery_address_screen()]}


# ── Screens ───────────────────────────────────────────────


def _product_browse_screen() -> dict:
    return {
        "id": "PRODUCT_BROWSE",
        "title": "Browse Products",
        "data": {
            "products": {"type": "array", "__example__": []},
            "categories": {"type": "array", "__example__": []},
            "store_name": {"type": "string", "__example__": "Store"},
            "cart_summary": {"type": "string", "__example__": ""},
        },
        "terminal": False,
        "layout": {
            "type": "SingleColumnLayout",
            "children": [
                {
                    "type": "Form",
                    "name": "browse_form",
                    "children": [
                        {
                            "type": "TextSubheading",
                            "text": "${data.store_name}",
                        },
                        {
                            "type": "TextBody",
                            "text": "${data.cart_summary}",
                        },
                        {
                            "type": "Dropdown",
                            "name": "category",
                            "label": "Category",
                            "required": False,
                            "data-source": "${data.categories}",
                            "on-select-action": {
                                "name": "data_exchange",
                                "payload": {
                                    "action_type": "filter_category",
                                    "category": "${form.category}",
                                },
                            },
                        },
                        {
                            "type": "RadioButtonsGroup",
                            "name": "product_id",
                            "label": "Select a product",
                            "required": True,
                            "data-source": "${data.products}",
                        },
                        {
                            "type": "Footer",
                            "label": "View Product",
                            "on-click-action": {
                                "name": "data_exchange",
                                "payload": {
                                    "action_type": "select_product",
                                    "product_id": "${form.product_id}",
                                },
                            },
                        },
                    ],
                }
            ],
        },
    }


def _product_detail_screen() -> dict:
    return {
        "id": "PRODUCT_DETAIL",
        "title": "Product Details",
        "data": {
            "product_name": {"type": "string", "__example__": ""},
            "product_price": {"type": "string", "__example__": ""},
            "product_description": {"type": "string", "__example__": ""},
            "product_id": {"type": "string", "__example__": ""},
        },
        "terminal": False,
        "layout": {
            "type": "SingleColumnLayout",
            "children": [
                {
                    "type": "Form",
                    "name": "detail_form",
                    "children": [
                        {
                            "type": "TextHeading",
                            "text": "${data.product_name}",
                        },
                        {
                            "type": "TextBody",
                            "text": "${data.product_price}",
                        },
                        {
                            "type": "TextBody",
                            "text": "${data.product_description}",
                        },
                        {
                            "type": "TextInput",
                            "name": "quantity",
                            "label": "Quantity",
                            "required": True,
                            "input-type": "number",
                            "helper-text": "Enter quantity (1-99)",
                        },
                        {
                            "type": "Footer",
                            "label": "Add to Cart",
                            "on-click-action": {
                                "name": "data_exchange",
                                "payload": {
                                    "action_type": "add_to_cart",
                                    "product_id": "${data.product_id}",
                                    "quantity": "${form.quantity}",
                                },
                            },
                        },
                    ],
                }
            ],
        },
    }


def _cart_review_screen() -> dict:
    return {
        "id": "CART_REVIEW",
        "title": "Your Cart",
        "data": {
            "cart_items": {"type": "string", "__example__": ""},
            "cart_total": {"type": "string", "__example__": ""},
            "is_empty": {"type": "boolean", "__example__": True},
        },
        "terminal": False,
        "layout": {
            "type": "SingleColumnLayout",
            "children": [
                {
                    "type": "Form",
                    "name": "cart_form",
                    "children": [
                        {
                            "type": "TextHeading",
                            "text": "Order Summary",
                        },
                        {
                            "type": "TextBody",
                            "text": "${data.cart_items}",
                        },
                        {
                            "type": "TextSubheading",
                            "text": "${data.cart_total}",
                        },
                        {
                            "type": "RadioButtonsGroup",
                            "name": "cart_action",
                            "label": "What next?",
                            "required": True,
                            "data-source": [
                                {"id": "checkout", "title": "Checkout"},
                                {"id": "add_more", "title": "Add more items"},
                                {"id": "clear", "title": "Clear cart"},
                            ],
                        },
                        {
                            "type": "Footer",
                            "label": "Continue",
                            "on-click-action": {
                                "name": "data_exchange",
                                "payload": {
                                    "action_type": "cart_action",
                                    "cart_action": "${form.cart_action}",
                                },
                            },
                        },
                    ],
                }
            ],
        },
    }


def _delivery_info_screen() -> dict:
    return {
        "id": "DELIVERY_INFO",
        "title": "Delivery Details",
        "data": {
            "delivery_options": {"type": "array", "__example__": []},
        },
        "terminal": False,
        "layout": {
            "type": "SingleColumnLayout",
            "children": [
                {
                    "type": "Form",
                    "name": "delivery_form",
                    "children": [
                        {
                            "type": "TextHeading",
                            "text": "Delivery Information",
                        },
                        {
                            "type": "RadioButtonsGroup",
                            "name": "delivery_method",
                            "label": "Delivery method",
                            "required": True,
                            "data-source": "${data.delivery_options}",
                        },
                        {
                            "type": "TextInput",
                            "name": "customer_name",
                            "label": "Full Name",
                            "required": True,
                            "input-type": "text",
                        },
                        {
                            "type": "TextInput",
                            "name": "phone",
                            "label": "Phone Number",
                            "required": True,
                            "input-type": "phone",
                        },
                        {
                            "type": "TextArea",
                            "name": "address",
                            "label": "Delivery Address",
                            "required": False,
                            "helper-text": "Required for delivery orders",
                        },
                        {
                            "type": "Footer",
                            "label": "Continue",
                            "on-click-action": {
                                "name": "data_exchange",
                                "payload": {
                                    "action_type": "submit_delivery",
                                    "delivery_method": "${form.delivery_method}",
                                    "customer_name": "${form.customer_name}",
                                    "phone": "${form.phone}",
                                    "address": "${form.address}",
                                },
                            },
                        },
                    ],
                }
            ],
        },
    }


def _payment_method_screen() -> dict:
    return {
        "id": "PAYMENT_METHOD",
        "title": "Payment",
        "data": {
            "cart_total": {"type": "string", "__example__": ""},
            "payment_options": {"type": "array", "__example__": []},
        },
        "terminal": False,
        "layout": {
            "type": "SingleColumnLayout",
            "children": [
                {
                    "type": "Form",
                    "name": "payment_form",
                    "children": [
                        {
                            "type": "TextHeading",
                            "text": "Payment",
                        },
                        {
                            "type": "TextBody",
                            "text": "${data.cart_total}",
                        },
                        {
                            "type": "RadioButtonsGroup",
                            "name": "payment_method",
                            "label": "Payment method",
                            "required": True,
                            "data-source": "${data.payment_options}",
                        },
                        {
                            "type": "TextInput",
                            "name": "ecocash_number",
                            "label": "EcoCash Number",
                            "required": False,
                            "input-type": "phone",
                            "helper-text": "Required for EcoCash payments",
                        },
                        {
                            "type": "Footer",
                            "label": "Review Order",
                            "on-click-action": {
                                "name": "data_exchange",
                                "payload": {
                                    "action_type": "submit_payment",
                                    "payment_method": "${form.payment_method}",
                                    "ecocash_number": "${form.ecocash_number}",
                                },
                            },
                        },
                    ],
                }
            ],
        },
    }


def _order_summary_screen() -> dict:
    return {
        "id": "ORDER_SUMMARY",
        "title": "Confirm Order",
        "data": {
            "summary_text": {"type": "string", "__example__": ""},
            "total_text": {"type": "string", "__example__": ""},
        },
        "terminal": True,
        "layout": {
            "type": "SingleColumnLayout",
            "children": [
                {
                    "type": "Form",
                    "name": "confirm_form",
                    "children": [
                        {
                            "type": "TextHeading",
                            "text": "Order Summary",
                        },
                        {
                            "type": "TextBody",
                            "text": "${data.summary_text}",
                        },
                        {
                            "type": "TextSubheading",
                            "text": "${data.total_text}",
                        },
                        {
                            "type": "Footer",
                            "label": "Place Order",
                            "on-click-action": {
                                "name": "complete",
                                "payload": {},
                            },
                        },
                    ],
                }
            ],
        },
    }
