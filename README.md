# SEO Outreach Agent 🤖📧

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Latest-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-ready LangGraph AI agent that automates the complete SEO outreach workflow:

1. **Extracts companies** from Google Maps based on keyword and location
2. **Enriches company data** by finding email addresses from websites
3. **Analyzes websites** for SEO issues and opportunities
4. **Generates comprehensive PDF reports** with detailed SEO audit findings
5. **Generates personalized emails** highlighting specific SEO problems
6. **Sends outreach emails** with PDF attachments and tracks responses

## 🌟 Features

- **Automated Lead Generation**: Extract companies from Google Maps with a single query
- **Email Discovery**: Automatically finds contact emails from company websites using multiple methods
- **SEO Analysis**: Comprehensive SEO audit identifying critical issues and opportunities
- **PDF Report Generation**: Generate professional PDF reports with detailed SEO analysis (optional)
- **Email Attachments**: Automatically attach PDF reports to outreach emails
- **Personalized Outreach**: AI-generated HTML emails tailored to each company's specific SEO problems
- **Structured Outputs**: Uses Pydantic models for reliable, structured LLM responses
- **Model Selection**: Configure which OpenAI model to use via environment variables
- **Email Sending**: Optional automated email delivery with tracking (disabled by default)
- **Free Tools**: Uses free scraping methods and SMTP for email sending
- **Phase Tracking**: Saves JSON files at each workflow phase for easy debugging
- **FastAPI REST API**: Production-ready REST API with enterprise-grade security, rate limiting, and OpenAPI documentation

## 🚀 Quick Start

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd seo_outreach_agent
   ```

2. **Install dependencies:**
   ```bash
   # Install all dependencies
   pip install -r requirements.txt
   
   # Install Playwright browser
   playwright install chromium
   ```

3. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env and add your OPENAI_API_KEY and SMTP credentials
   ```

### Usage Options

#### Option 1: FastAPI REST API (Recommended for Production)

Start the FastAPI server:

```bash
python run_api.py
# Or: python -m app.main
# Or: uvicorn app.main:app --reload
```

The API will be available at:
- **API**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

**Example API Request:**

```bash
curl -X POST http://localhost:8000/api/v1/seo-outreach/process \
  -H "Content-Type: application/json" \
  -d '{
    "query": "restaurants",
    "location": "New York, NY",
    "max_results": 10,
    "send_emails": false,
    "generate_pdf": true
  }'
```

**Python Example:**

```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/seo-outreach/process",
    json={
        "query": "restaurants",
        "location": "New York, NY",
        "max_results": 10,
        "send_emails": False,
        "generate_pdf": True  # Enable PDF generation
    }
)
print(response.json())
```

See [API_README.md](API_README.md) for complete API documentation.

#### Option 2: Standalone Python Agent

Run the agent directly:

```bash
python seo_outreach_agent.py
```

**Python Usage:**

```python
import asyncio
from seo_outreach_agent import SEOOutreachAgent

async def main():
    agent = SEOOutreachAgent()
    
    result = await agent.process(
        query="restaurants",  # Search keyword
        location="New York, NY",  # Location
        max_results=10,  # Number of companies to process
        send_emails=False,  # Set to True to actually send emails
        generate_pdf=True,  # Generate PDF reports
    )
    
    print(f"Status: {result['status']}")
    print(f"Companies found: {result['results']['total_companies']}")
    print(f"Emails sent: {result['results']['emails_sent']}")

asyncio.run(main())
```

## 📋 Requirements

### Required Environment Variables

- `OPENAI_API_KEY`: Your OpenAI API key (required for SEO analysis and email generation)

### Optional Environment Variables

- `OPENAI_MODEL`: OpenAI model to use (defaults to `gpt-4o`)

### Email Sending Configuration

To send emails, configure SMTP settings in `.env`:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
FROM_EMAIL=your_email@gmail.com
FROM_NAME=SEO Outreach
```

**Note for Gmail users**: You'll need to create an [App Password](https://support.google.com/accounts/answer/185833) instead of your regular password.

## 🔄 Workflow

The agent follows this automated workflow:

### Step 1: Extract Companies from Google Maps
- Searches Google Maps using your keyword and location
- Extracts company information: name, address, phone, website, rating
- Returns structured company data

### Step 2: Enrich with Email Addresses
- Visits each company website
- Scrapes homepage, contact page, and about page
- Extracts email addresses using multiple methods:
  - Static HTML parsing
  - Playwright stealth scraping
  - WHOIS lookup (fallback)
  - Email pattern guessing with validation (fallback)

### Step 3: Analyze SEO Issues
- Extracts website content and SEO elements
- Analyzes title tags, meta descriptions, headings, images, links
- Identifies technical SEO issues
- Generates SEO score (0-100) and priority fixes

### Step 4: Generate PDF Reports (Optional)
- Generates comprehensive PDF reports with detailed SEO analysis
- Includes SEO scores, issues, recommendations, and action plans
- PDFs are saved to `output/` directory
- PDFs are automatically attached to outreach emails when enabled

### Step 5: Generate Personalized Emails
- Uses AI to create personalized outreach emails
- Highlights 2-3 most critical SEO issues for each company
- Explains the impact and offers solutions
- Professional, friendly, and value-focused tone
- Includes PDF attachment if PDF generation is enabled

### Step 6: Send Emails
- Sends emails via SMTP (Gmail, Outlook, etc.)
- Automatically attaches PDF reports if generated
- Tracks sent status and timestamps
- Handles errors gracefully

## 📊 Output

### Phase Outputs (JSON)

The agent saves JSON files at each phase:
- `1_extracted_companies_{query}_{timestamp}.json` - Companies from Google Maps
- `2_enriched_companies_{query}_{timestamp}.json` - Companies with emails
- `3_seo_analysis_{query}_{timestamp}.json` - SEO analysis results
- `4_generated_emails_{query}_{timestamp}.json` - Generated emails

### PDF Reports (When Enabled)

PDF reports are saved to `output/seo_audit_{domain}_{timestamp}.pdf` with:
- **Company Information**: Name, website URL
- **SEO Score**: Overall SEO score (0-100)
- **Page Information**: Title, meta description, word count, images, links
- **SEO Audit Results**: Detailed analysis of:
  - Title analysis
  - Meta description analysis
  - Heading structure
  - Content analysis
  - Image optimization
  - Technical SEO
  - Keyword analysis
- **Priority Fixes**: High-priority issues with solutions
- **Strengths**: What the website is doing well
- **Quick Wins**: Easy improvements with high impact

### Final Results (JSON)

A single consolidated JSON file: `final_results_{query}_{timestamp}.json` containing:
- `name`: Company name
- `address`: Company address
- `phone`: Phone number
- `website`: Website URL
- `email`: Contact email
- `seo_score`: SEO score (0-100)
- `pdf_path`: Path to generated PDF report (if PDF generation enabled)
- `email_subject`: Generated email subject
- `email_body`: Generated HTML email body
- `email_sending_status`: Status (sent, failed, skipped, skipped_no_email, error)

### Markdown Report

Results are also saved to `output/seo_outreach_[query]_[timestamp].md` with:

- **Summary**: Total companies, emails found, emails sent
- **Company Details**: For each company:
  - Company name and website
  - Contact email
  - SEO score
  - Generated email content
  - Email sent status

## 🛠️ Architecture

### Agent Architecture

The agent is built using LangGraph with the following structure:

- **State Management**: `SEOOutreachState` tracks progress through all steps
- **Graph Nodes**: Each workflow step is a separate node
- **Tools**: Reuses existing Google Maps scraper and email finder code
- **LLM Service**: Handles SEO analysis and email generation
- **PDF Generator**: Generates professional PDF reports from audit data
- **Error Handling**: Comprehensive error handling at each step

### FastAPI Application Structure

```
seo_outreach_agent/
├── app/                    # FastAPI application
│   ├── main.py            # FastAPI app instance
│   ├── config.py          # Configuration management
│   ├── middleware.py      # Security, CORS, rate limiting
│   ├── api/               # API routes
│   │   └── v1/
│   │       ├── api.py     # API router
│   │       └── endpoints/ # Endpoint handlers
│   ├── models/            # Pydantic request/response models
│   ├── core/              # Core components (exceptions)
│   └── utils/             # Utilities (validation, sanitization)
├── seo_outreach_agent.py  # Main agent (standalone)
├── pdf_generator.py       # PDF generation module
├── website_audit_agent.py # Website SEO audit agent
├── google_maps_scraper_agent.py  # Google Maps scraper
├── email_finder_agent.py  # Email finder agent
├── tools/                 # Agent tools
│   └── seo_outreach_tools.py  # SEO outreach specific tools
├── requirements.txt       # All dependencies (agent + FastAPI)
├── run_api.py            # API startup script
└── profile.md            # Profile template for email personalization
```

### API Endpoints

- **Health Check**: `GET /api/v1/health` - Check API status and version
- **Process SEO Outreach**: `POST /api/v1/seo-outreach/process` - Complete end-to-end workflow
  - Extracts companies from Google Maps
  - Finds email addresses
  - Analyzes SEO issues
  - Generates PDF reports (optional)
  - Generates personalized emails
  - Sends emails with attachments (optional)

### Security Features

- ✅ **Input Validation**: All inputs validated with Pydantic
- ✅ **Input Sanitization**: XSS prevention, HTML tag removal
- ✅ **Rate Limiting**: Per-IP rate limiting (configurable)
- ✅ **CORS Protection**: Configurable allowed origins
- ✅ **Security Headers**: XSS protection, content type options, frame options
- ✅ **Error Handling**: Secure error messages without leaking sensitive info
- ✅ **Request Logging**: Comprehensive request/response logging

## 🔧 Configuration

### Adjusting Search Parameters

```python
result = await agent.process(
    query="dentists",  # Your search keyword
    location="Los Angeles, CA",  # Target location
    max_results=20,  # Number of companies to process
    send_emails=False,  # Set to True to actually send emails
    generate_pdf=True,  # Generate PDF reports
)
```


### Email Customization

The agent automatically generates personalized emails, but you can customize the tone by modifying the `LLMService.generate_personalized_email()` method in `seo_outreach_agent.py`.

### PDF Generation

PDF generation is optional and controlled by the `generate_pdf` parameter:

- **When enabled**: PDFs are generated after SEO analysis and attached to emails
- **PDF Location**: Saved to `output/seo_audit_{domain}_{timestamp}.pdf`
- **PDF Content**: Includes comprehensive SEO audit with scores, issues, and recommendations
- **Email Attachment**: PDFs are automatically attached when sending emails

## 📝 Example Output

```
# SEO Outreach Results

**Query:** restaurants
**Location:** New York, NY
**Generated:** 2024-01-15T10:30:00
**Status:** completed

## Summary

- Total Companies Found: 10
- Companies with Emails: 8
- Companies with SEO Analysis: 10
- PDF Reports Generated: 10
- Emails Generated: 8
- Emails Sent: 8

## Companies

### 1. Joe's Pizza

- **Website:** https://joespizza.com
- **Email:** contact@joespizza.com
- **SEO Score:** 45/100
- **PDF Report:** output/seo_audit_joespizza.com_20240115_103000.pdf
- **Email Sent:** Yes

**Generated Email:**

Subject: Quick SEO Fix for Joe's Pizza

Hi there,

I recently analyzed your website and noticed a few SEO issues that might be affecting your online visibility...

[Personalized email content]

[PDF report attached]
```

## ⚠️ Important Notes

1. **Rate Limiting**: The agent includes delays between requests to avoid rate limiting. Processing many companies may take time.

2. **PDF Generation**: 
   - Requires `weasyprint` library (included in requirements)
   - PDFs are generated synchronously and may add processing time
   - PDFs are saved to disk and also stored in memory for email attachment

3. **Email Deliverability**: 
   - Use a professional email address
   - Avoid spam trigger words
   - Consider warming up your email account
   - Follow email marketing best practices
   - PDF attachments may increase email size

4. **Legal Compliance**:
   - Ensure compliance with CAN-SPAM Act and GDPR
   - Include unsubscribe options if required
   - Respect opt-out requests

5. **Free Tools**: This agent uses free scraping methods. For production use with high volume, consider:
   - Using proxies for rate limiting
   - Implementing retry logic
   - Using professional email services (SendGrid, Mailgun, etc.)

## 🐛 Troubleshooting

### No companies found
- Check your search query and location
- Google Maps may have rate limits
- Try a different location or keyword

### No emails found
- Some websites don't display emails publicly
- Try enabling WHOIS lookup (may require additional setup)
- Check if websites have contact forms instead

### SEO analysis fails
- Ensure OPENAI_API_KEY is set correctly
- Check if website is accessible
- Some websites may block automated access

### PDF generation fails
- Ensure PDF dependencies are installed: `pip install weasyprint jinja2 markdown bleach`
- Check system dependencies for weasyprint (may require additional system packages on Linux)
- On Ubuntu/Debian: `sudo apt-get install python3-cffi python3-brotli libpango-1.0-0 libpangoft2-1.0-0`
- PDF generation errors are logged but don't stop the workflow

### Email sending fails
- Verify SMTP credentials
- For Gmail, use App Password, not regular password
- Check firewall/network settings
- Verify SMTP host and port
- Large PDF attachments may cause email size limits

## 📚 Dependencies

All dependencies are listed in `requirements.txt`, including:

### Core Dependencies

- **LangChain & LangGraph**: 
  - `langchain`: LLM integration and tooling
  - `langchain-openai`: OpenAI integration
  - `langchain-community`: Community integrations
  - `langgraph`: Workflow orchestration

- **FastAPI & Web Server**:
  - `fastapi`: FastAPI web framework
  - `uvicorn`: ASGI server
  - `slowapi`: Rate limiting middleware

- **Data Validation**:
  - `pydantic`: Data validation and settings
  - `pydantic-settings`: Settings management

- **Browser Automation**:
  - `playwright`: Browser automation for scraping
  - `playwright-stealth`: Stealth mode for scraping
  - `selenium`: Alternative browser automation

- **HTTP & Parsing**:
  - `aiohttp`: Async HTTP client
  - `httpx`: Modern HTTP client
  - `beautifulsoup4`: HTML parsing

- **PDF Generation** (if using PDF features):
  - `weasyprint`: PDF generation from HTML
  - `jinja2`: Template engine for PDF generation
  - `markdown`: Markdown to HTML conversion
  - `bleach`: HTML sanitization

- **Email & DNS**:
  - `python-whois`: WHOIS lookup for email finding
  - `dnspython`: DNS resolution for email validation

- **Utilities**:
  - `python-dotenv`: Environment variable management
  - `typing-extensions`: Type hints support

See `requirements.txt` for complete dependency list with versions.

## 📄 License

MIT License - See LICENSE file for details

## 🤝 Contributing

Contributions welcome! Please follow the existing code structure and add tests for new features.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📖 Documentation

- **[API_README.md](API_README.md)**: Complete FastAPI API documentation
- **[QUICKSTART.md](QUICKSTART.md)**: Quick start guide for the API
- **Swagger UI**: http://localhost:8000/docs (when API is running)
- **ReDoc**: http://localhost:8000/redoc (when API is running)

## 📧 Support

For issues or questions, please open an issue on GitHub.

## 🔗 Related Files

- `seo_outreach_agent.py` - Standalone agent implementation
- `pdf_generator.py` - PDF generation module
- `app/main.py` - FastAPI application entry point
- `app/api/v1/endpoints/seo_outreach.py` - API endpoint handlers
- `tools/seo_outreach_tools.py` - Agent tools

## 🎯 Roadmap

- [ ] Add support for multiple email templates
- [ ] Implement email tracking (open rates, click rates)
- [ ] Add support for custom PDF templates
- [ ] Implement batch processing with progress tracking
- [ ] Add webhook support for async processing
- [ ] Add support for multiple SMTP providers

---

**Built with ❤️ using LangGraph, LangChain, FastAPI, and WeasyPrint**
# SEO-Outreach-AI-Agent
