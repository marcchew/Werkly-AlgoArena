# Werkly - AI-Powered Job Matching Platform

Werkly is a comprehensive web application that uses artificial intelligence to connect job seekers with their perfect job opportunities and help companies find ideal candidates. Built with Flask, Bootstrap, SQLite, and the OpenAI API.

## Features

### For Job Seekers
- AI-Powered Job Matching with personalized recommendations
- Smart Profile Analysis using resume and personal information
- **Resume Upload Support** for PDF and DOCX files with automatic text extraction
- Match Scoring with compatibility percentages (0-100%)
- Detailed AI Insights explaining why each job is a good fit
- Resume Integration for better matching accuracy

### For Companies
- Intelligent Candidate Matching for job postings
- Comprehensive Job Posting with live preview
- Dashboard Analytics for tracking postings and candidates
- Company Profile Management to showcase culture and values

### Technical Features
- Modern UI/UX with Bootstrap and custom gradients
- Secure Authentication with password hashing
- **File Upload Processing** with support for PDF and DOCX resume extraction
- Real-time AI Matching when jobs are posted
- Responsive Design for all devices
- SQLite Database with proper relationships

## Resume Upload Feature

Werkly now supports uploading resumes in PDF and DOCX formats:

- **Automatic Text Extraction**: Upload your resume file and the system automatically extracts and processes the text
- **File Validation**: Ensures only PDF and DOCX files are accepted (max 16MB)
- **Intelligent Processing**: Combines uploaded resume content with any additional notes you provide
- **AI Integration**: Extracted resume text is used by the AI matching algorithm for better job recommendations

### Supported File Formats
- **PDF**: All standard PDF documents with extractable text
- **DOCX**: Microsoft Word documents (.docx format)
- **File Size Limit**: Maximum 16MB per file

## Quick Start

### Prerequisites
- Python 3.8 or higher
- OpenAI API key
- Modern web browser

### Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure OpenAI API:
   Open `app.py` and replace `"your-openai-api-key"` with your actual OpenAI API key.

3. Run the application:
   ```bash
   python app.py
   ```

4. Open your browser and navigate to `http://localhost:5000`

## How to Use

### For Job Seekers
1. Register as a "Job Seeker"
2. Complete your profile with skills, experience, and upload your resume (PDF/DOCX) or enter content manually
3. Click "Find New Matches" to get AI-powered job recommendations
4. Review matches with compatibility scores and AI reasoning

### For Companies
1. Register as a "Company" 
2. Setup your company profile
3. Post detailed job listings with requirements and tags
4. AI automatically finds and matches qualified candidates

## Technical Architecture

- **Backend**: Flask with SQLite database
- **AI Integration**: OpenAI GPT-3.5-turbo for intelligent matching
- **Frontend**: Bootstrap 5 with modern UI components
- **Security**: Password hashing and secure sessions

## Configuration

Replace the placeholder API key in `app.py`:
```python
openai.api_key = "your-actual-openai-api-key"
```

Get your OpenAI API key from: https://platform.openai.com/api-keys

## Features Highlight

- **Automatic Matching**: AI analyzes profiles and job postings to create matches
- **Real-time Updates**: Dashboard shows live statistics and new matches
- **Professional Design**: Modern interface with gradients and animations
- **Complete Workflow**: From registration to job matching in a few clicks

## Support

For issues or questions:
1. Verify OpenAI API key is valid
2. Check all dependencies are installed
3. Check Python version (3.8+ required)
4. Review console output for errors
