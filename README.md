# Aria

A Discord selfbot with advanced features including activity control, analytics, and automation.

## Features

- **Activity Control**: Set custom Discord activities, VR presence, and more
- **Analytics**: Track messages, commands, and bot performance
- **Web Dashboard**: Modern web interface for bot management
- **Proxy Support**: Built-in proxy rotation for safety
- **Captcha Solving**: Automatic captcha solving for uninterrupted operation

## Captcha Integration

Aria includes automatic captcha solving to handle Discord's captcha challenges. When enabled, the bot will automatically solve captchas using supported services.

### Setup

1. Get an API key from [2Captcha](https://2captcha.com/)
2. Edit `config.json`:
```json
{
  "captcha_enabled": true,
  "captcha_api_key": "your_2captcha_api_key_here",
  "captcha_service": "2captcha"
}
```

### Supported Services

- **2Captcha** (recommended)
- AntiCaptcha
- CapMonster

### Web Dashboard

Configure captcha settings through the web dashboard at `http://localhost:8080` under the Settings section.

### How it Works

When Discord presents a captcha challenge (HTTP 400 with captcha data), Aria will:
1. Detect the captcha type (hCaptcha, reCAPTCHA, or Cloudflare Turnstile)
2. Send the challenge to your configured captcha service
3. Wait for the solution
4. Retry the request with the solved captcha token

This ensures your bot continues operating even when Discord requires captcha verification.