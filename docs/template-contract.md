# Universal Lead Schema Contract

Every template and Python renderer in this system MUST follow this exact schema contract.

## Lead Record Schema

```python
{
    "slug": "",
    "fullName": "",
    "shortName": "",
    "category": "",
    "city": "",
    "address": "",
    "phone": "",
    "phoneDisplay": "",
    "phoneIntl": "",
    "whatsappUrl": "",
    "waEnabled": False,
    "rating": "",
    "reviewCount": "",
    "review": "",
    "hours": "",
    "website": "",
    "websiteLabel": "",
    "mapsUrl": "",
    "latitude": "",
    "longitude": "",
    "pageUrl": "",
    "pageTitle": "",
    "pageDescription": "",
    "siteName": "",
    "builtAt": ""
}
```

## Contract Rules

1. **Invariant Fields**: Every single field listed above MUST ALWAYS exist in the lead dictionary returned by `engine.lead_record()`.
2. **Empty Fallbacks**: Missing or unprovided data MUST default to an empty string `""` (or `False` for `waEnabled`), never `None` or omitted keys.
3. **Template Compatibility**: Jinja2 templates consume `lead.<fieldName>` directly. Using `StrictUndefined` ensures missing keys raise immediate runtime exceptions.
