from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
from openai import OpenAI
from datetime import datetime
import json
import re
import PyPDF2
from docx import Document
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = 'abcd123'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 128 * 1024 * 1024

@app.before_request
def log_request_info():
    print(f"=== INCOMING REQUEST ===")
    print(f"Method: {request.method}")
    print(f"URL: {request.url}")
    print(f"Path: {request.path}")
    print(f"Args: {request.args}")
    print(f"========================")

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Model used for AI matching (cheaper default can be overridden via env)
AI_MATCH_MODEL = os.getenv("OPENAI_MATCH_MODEL", "gpt-4.1-nano")

# Allowed file extensions for resume uploads
ALLOWED_EXTENSIONS = {'pdf', 'docx'}

# Add custom Jinja2 filter for JSON parsing
@app.template_filter('fromjson')
def fromjson_filter(value):
    """Parse JSON string in Jinja2 templates."""
    try:
        if value:
            return json.loads(value)
        return {}
    except (json.JSONDecodeError, TypeError):
        return {}

def allowed_file(filename):
    """Check if the uploaded file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(file_path):
    """Extract text from PDF file."""
    try:
        text = ""
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""

def extract_text_from_docx(file_path):
    """Extract text from DOCX file."""
    try:
        doc = Document(file_path)
        text = ""
        for paragraph in doc.paragraphs:
            text += paragraph.text + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from DOCX: {e}")
        return ""

def extract_text_from_file(file_path, filename):
    """Extract text from uploaded file based on extension."""
    file_extension = filename.rsplit('.', 1)[1].lower()
    
    if file_extension == 'pdf':
        return extract_text_from_pdf(file_path)
    elif file_extension == 'docx':
        return extract_text_from_docx(file_path)
    else:
        return ""

def init_db():
    """Initialize the database with required tables."""
    conn = sqlite3.connect('jobmatch.db')
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            user_type TEXT NOT NULL CHECK (user_type IN ('seeker', 'company')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Job seekers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS job_seekers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            resume_text TEXT,
            personal_statement TEXT,
            skills TEXT,
            experience_years INTEGER,
            education TEXT,
            preferred_location TEXT,
            preferred_employment_types TEXT DEFAULT '["Full-time"]',
            salary_expectation INTEGER,
            priorities TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Migration: Add preferred_employment_types column if it doesn't exist
    try:
        cursor.execute('ALTER TABLE job_seekers ADD COLUMN preferred_employment_types TEXT DEFAULT \'["Full-time"]\'')
        conn.commit()
    except sqlite3.OperationalError:
        pass
    
    # Companies table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_name TEXT NOT NULL,
            description TEXT,
            industry TEXT,
            size TEXT,
            location TEXT,
            website TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Jobs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            requirements TEXT NOT NULL,
            tags TEXT,
            location TEXT,
            salary_range TEXT,
            employment_type TEXT,
            experience_required INTEGER,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies (id)
        )
    ''')
    
    # Matches table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_seeker_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            match_score REAL NOT NULL,
            ai_reasoning TEXT,
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_seeker_id) REFERENCES job_seekers (id),
            FOREIGN KEY (job_id) REFERENCES jobs (id),
            UNIQUE(job_seeker_id, job_id)
        )
    ''')
    
    # Analysis cache table - for caching AI analysis results
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analysis_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            job_seeker_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            match_score REAL NOT NULL,
            ai_reasoning TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies (id),
            FOREIGN KEY (job_seeker_id) REFERENCES job_seekers (id),
            FOREIGN KEY (job_id) REFERENCES jobs (id),
            UNIQUE(company_id, job_seeker_id, job_id)
        )
    ''')
    
    # Saved jobs table (for job seekers)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS saved_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_seeker_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_seeker_id) REFERENCES job_seekers (id),
            FOREIGN KEY (job_id) REFERENCES jobs (id),
            UNIQUE(job_seeker_id, job_id)
        )
    ''')
    
    # Saved candidates table (for companies)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS saved_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            job_seeker_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies (id),
            FOREIGN KEY (job_seeker_id) REFERENCES job_seekers (id),
            UNIQUE(company_id, job_seeker_id)
        )
    ''')
    
    # Messages table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users (id),
            FOREIGN KEY (receiver_id) REFERENCES users (id)
        )
    ''')
    
    # Applications table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_seeker_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            cover_letter TEXT,
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'reviewed', 'accepted', 'rejected', 'offered')),
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (job_seeker_id) REFERENCES job_seekers (id),
            FOREIGN KEY (job_id) REFERENCES jobs (id),
            UNIQUE(job_seeker_id, job_id)
        )
    ''')
    
    # Job offers table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS job_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            job_seeker_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            offer_message TEXT,
            salary_offered TEXT,
            start_date TEXT,
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'declined', 'withdrawn')),
            offered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            responded_at TIMESTAMP,
            notes TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs (id),
            FOREIGN KEY (job_seeker_id) REFERENCES job_seekers (id),
            FOREIGN KEY (company_id) REFERENCES companies (id),
            UNIQUE(job_id, job_seeker_id)
        )
    ''')
    
    # Ratings table (users rate each other)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rater_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            review TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(rater_id, target_id),
            FOREIGN KEY (rater_id) REFERENCES users (id),
            FOREIGN KEY (target_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect('jobmatch.db')
    conn.row_factory = sqlite3.Row
    return conn

def analyze_match_with_ai(seeker_data, job_data):
    """Use OpenAI to analyze job match compatibility with caching."""
    try:
        print(f"Analyzing match for seeker {seeker_data.get('full_name', 'Unknown')} and job {job_data.get('title', 'Unknown')}")
        
        # Get company_id from job_data
        company_id = job_data.get('company_id')
        job_seeker_id = seeker_data.get('id')
        job_id = job_data.get('id')
        
        # Check cache first
        if company_id and job_seeker_id and job_id:
            conn = get_db_connection()
            cached_result = conn.execute('''
                SELECT match_score, ai_reasoning FROM analysis_cache 
                WHERE company_id = ? AND job_seeker_id = ? AND job_id = ?
            ''', (company_id, job_seeker_id, job_id)).fetchone()
            
            if cached_result:
                print(f"Using cached analysis result for company {company_id}, seeker {job_seeker_id}, job {job_id}")
                conn.close()
                return cached_result['match_score'], cached_result['ai_reasoning']
            conn.close()
        
        # Get ratings and reviews data
        conn = get_db_connection()
        
        # Get company ratings and reviews (from job seekers)
        company_user_id = None
        if company_id:
            company_user = conn.execute('SELECT user_id FROM companies WHERE id = ?', (company_id,)).fetchone()
            if company_user:
                company_user_id = company_user['user_id']
        
        company_rating_info = ""
        if company_user_id:
            company_stats = conn.execute('''
                SELECT ROUND(AVG(rating),1) as avg_rating, COUNT(*) as count 
                FROM ratings WHERE target_id = ?
            ''', (company_user_id,)).fetchone()
            
            if company_stats['count'] > 0:
                company_reviews = conn.execute('''
                    SELECT rating, review, created_at 
                    FROM ratings WHERE target_id = ? AND review IS NOT NULL AND review != ''
                    ORDER BY created_at DESC LIMIT 15
                ''', (company_user_id,)).fetchall()
                
                company_rating_info = f"""
        Company Rating Information:
        - Average Rating: {company_stats['avg_rating']}/5.0 ({company_stats['count']} reviews)
        - Recent Reviews:"""
                
                for i, review in enumerate(company_reviews, 1):
                    company_rating_info += f"""
          {i}. Rating: {review['rating']}/5 - "{review['review'][:200]}{'...' if len(review['review']) > 200 else ''}" """
        
        # Get job seeker ratings and reviews (from companies)
        seeker_user_id = None
        if job_seeker_id:
            seeker_user = conn.execute('SELECT user_id FROM job_seekers WHERE id = ?', (job_seeker_id,)).fetchone()
            if seeker_user:
                seeker_user_id = seeker_user['user_id']
        
        seeker_rating_info = ""
        if seeker_user_id:
            seeker_stats = conn.execute('''
                SELECT ROUND(AVG(rating),1) as avg_rating, COUNT(*) as count 
                FROM ratings WHERE target_id = ?
            ''', (seeker_user_id,)).fetchone()
            
            if seeker_stats['count'] > 0:
                seeker_reviews = conn.execute('''
                    SELECT rating, review, created_at 
                    FROM ratings WHERE target_id = ? AND review IS NOT NULL AND review != ''
                    ORDER BY created_at DESC LIMIT 15
                ''', (seeker_user_id,)).fetchall()
                
                seeker_rating_info = f"""
        Job Seeker Rating Information:
        - Average Rating: {seeker_stats['avg_rating']}/5.0 ({seeker_stats['count']} reviews)
        - Recent Reviews from Companies:"""
                
                for i, review in enumerate(seeker_reviews, 1):
                    seeker_rating_info += f"""
          {i}. Rating: {review['rating']}/5 - "{review['review'][:200]}{'...' if len(review['review']) > 200 else ''}" """
        
        conn.close()
        
        # Parse priorities
        priorities = {}
        try:
            priorities = json.loads(seeker_data.get('priorities', '{}'))
        except:
            priorities = {}
        
        # Parse preferred employment types
        preferred_employment_types = []
        try:
            preferred_employment_types = json.loads(seeker_data.get('preferred_employment_types', '["Full-time"]'))
        except:
            preferred_employment_types = ['Full-time']
        
        priorities_text = ""
        if priorities:
            priorities_text = f"""
        Job Seeker Priorities (importance 1-5):
        - Salary: {priorities.get('salary', 3)}/5
        - Work-Life Balance: {priorities.get('work_life_balance', 3)}/5  
        - Remote Work: {priorities.get('remote_work', 3)}/5
        - Company Culture: {priorities.get('company_culture', 3)}/5
        - Career Growth: {priorities.get('career_growth', 3)}/5
        - Job Security: {priorities.get('job_security', 3)}/5
        - Learning Opportunities: {priorities.get('learning_opportunities', 3)}/5
        - Team Environment: {priorities.get('team_environment', 3)}/5
        - Work Autonomy: {priorities.get('work_autonomy', 3)}/5
        - Benefits Package: {priorities.get('benefits', 3)}/5
            """
        
        prompt = f"""
        Analyze the compatibility between this job seeker and job posting. Consider the seeker's stated priorities AND the ratings/reviews data when scoring. Return a JSON response with match_score (0-100) and reasoning.

        Job Seeker Profile:
        - Name: {seeker_data.get('full_name', 'N/A')}
        - Experience: {seeker_data.get('experience_years', 0)} years
        - Skills: {seeker_data.get('skills', 'N/A')}
        - Education: {seeker_data.get('education', 'N/A')}
        - Personal Statement: {seeker_data.get('personal_statement', 'N/A')}
        - Resume Extract: {seeker_data.get('resume_text', 'N/A')[:500]}...
        - Preferred Employment Types: {', '.join(preferred_employment_types)}
        {priorities_text}
        {seeker_rating_info}

        Job Posting:
        - Title: {job_data.get('title', 'N/A')}
        - Description: {job_data.get('description', 'N/A')}
        - Requirements: {job_data.get('requirements', 'N/A')}
        - Experience Required: {job_data.get('experience_required', 0)} years
        - Employment Type: {job_data.get('employment_type', 'N/A')}
        - Location: {job_data.get('location', 'N/A')}
        - Salary Range: {job_data.get('salary_range', 'N/A')}
        - Tags: {job_data.get('tags', 'N/A')}
        {company_rating_info}

        IMPORTANT SCORING FACTORS:
        1. Factor in the seeker's priorities heavily when scoring. Higher priority items should have more weight in the final score.
        2. EMPLOYMENT TYPE MATCHING: If the job's employment type matches the seeker's preferred employment types, this should significantly boost the match score.
        3. RATINGS IMPACT: Consider both the job seeker's rating history and the company's rating history:
           - High-rated job seekers (4.0+ average) should get a slight boost (+5-10 points)
           - High-rated companies (4.0+ average) should make the match more attractive (+5-10 points)
           - Low-rated entities (below 3.0) should receive penalties (-5-15 points)
           - Reviews mentioning work quality, reliability, communication, or culture should influence the score
        4. If either party has no ratings yet, don't penalize - treat as neutral

        Provide analysis in this exact JSON format:
        {{
            "match_score": <number between 0-100>,
            "reasoning": "<detailed explanation considering skills match, priorities alignment, AND how ratings/reviews factor into the compatibility>"
        }}
        """
        
        print("Sending request to OpenAI...")
        response = client.chat.completions.create(
            model=AI_MATCH_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert HR recruiter analyzing job compatibility. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=300
        )
        print(response)
        print("Received response from OpenAI")
        response_content = response.choices[0].message.content.strip()
        
        # Handle empty or invalid response
        if not response_content:
            print("Warning: Empty response from OpenAI")
            score = 50
            reasoning = "Analysis could not be completed due to empty response"
        else:
            try:
                # Try to parse JSON response directly
                result = json.loads(response_content)
                score = result.get('match_score', 50)
                reasoning = result.get('reasoning', 'Analysis completed')
            except json.JSONDecodeError as json_error:
                print(f"JSON parsing error: {json_error}")
                print(f"Raw response: {response_content}")
                
                # Try to extract JSON from markdown code blocks
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_content, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group(1))
                        score = result.get('match_score', 50)
                        reasoning = result.get('reasoning', 'Analysis completed')
                        print("Successfully parsed JSON from markdown code block")
                    except json.JSONDecodeError:
                        # Fallback to regex extraction
                        score_match = re.search(r'"match_score":\s*(\d+)', response_content)
                        reasoning_match = re.search(r'"reasoning":\s*"([^"]*)"', response_content)
                        if score_match:
                            score = int(score_match.group(1))
                            reasoning = reasoning_match.group(1) if reasoning_match else "Analysis completed (extracted from malformed JSON)"
                        else:
                            score = 50
                            reasoning = "Analysis could not be completed due to invalid response format"
                else:
                    # Try to extract score and reasoning from text if JSON parsing fails
                    score_match = re.search(r'"match_score":\s*(\d+)', response_content)
                    reasoning_match = re.search(r'"reasoning":\s*"([^"]*)"', response_content)
                    if score_match:
                        score = int(score_match.group(1))
                        reasoning = reasoning_match.group(1) if reasoning_match else "Analysis completed (extracted from malformed JSON)"
                    else:
                        score = 50
                        reasoning = "Analysis could not be completed due to invalid response format"
        
        print(f"Match score: {score}%")
        
        # Cache the result if we have all required IDs
        if company_id and job_seeker_id and job_id:
            try:
                conn = get_db_connection()
                conn.execute('''
                    INSERT OR REPLACE INTO analysis_cache 
                    (company_id, job_seeker_id, job_id, match_score, ai_reasoning)
                    VALUES (?, ?, ?, ?, ?)
                ''', (company_id, job_seeker_id, job_id, score, reasoning))
                conn.commit()
                conn.close()
                print(f"Cached analysis result for company {company_id}, seeker {job_seeker_id}, job {job_id}")
            except Exception as cache_error:
                print(f"Error caching result: {cache_error}")
        
        return score, reasoning
        
    except Exception as e:
        print(f"AI Analysis Error: {e}")
        # Fallback 
        score = 50 
        reasoning = "Analysis could not be completed due to an error"
        return score, reasoning

@app.route('/')
def index():
    """Home page."""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration."""
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']
        
        if not all([username, email, password, user_type]):
            flash('Please fill in all fields.', 'error')
            return render_template('register.html')
        
        conn = get_db_connection()
        
        # Check if user already exists
        existing_user = conn.execute(
            'SELECT id FROM users WHERE username = ? OR email = ?',
            (username, email)
        ).fetchone()
        
        if existing_user:
            flash('Username or email already exists.', 'error')
            conn.close()
            return render_template('register.html')
        
        # Create new user
        password_hash = generate_password_hash(password)
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO users (username, email, password_hash, user_type) VALUES (?, ?, ?, ?)',
            (username, email, password_hash, user_type)
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        session['user_id'] = user_id
        session['username'] = username
        session['user_type'] = user_type
        
        flash('Registration successful!', 'success')
        return redirect(url_for('profile_setup'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute(
            'SELECT * FROM users WHERE username = ?',
            (username,)
        ).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['user_type'] = user['user_type']
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """User logout."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/profile-setup', methods=['GET', 'POST'])
def profile_setup():
    """Profile setup after registration."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        user_id = session['user_id']
        user_type = session['user_type']
        
        conn = get_db_connection()
        
        if user_type == 'seeker':
            full_name = request.form['full_name']
            personal_statement = request.form['personal_statement']
            skills = request.form['skills']
            experience_years = int(request.form.get('experience_years', 0))
            education = request.form['education']
            preferred_location = request.form['preferred_location']
            
            # Handle preferred employment types
            preferred_employment_types = request.form.getlist('preferred_employment_types')
            if not preferred_employment_types:
                preferred_employment_types = ['Full-time']
            preferred_employment_types_json = json.dumps(preferred_employment_types)
            
            salary_expectation = int(request.form.get('salary_expectation', 0))
            resume_text = request.form.get('resume_text', '')
            
            # Handle priorities
            priorities = {
                'salary': int(request.form.get('priority_salary', 3)),
                'work_life_balance': int(request.form.get('priority_work_life_balance', 3)),
                'remote_work': int(request.form.get('priority_remote_work', 3)),
                'company_culture': int(request.form.get('priority_company_culture', 3)),
                'career_growth': int(request.form.get('priority_career_growth', 3)),
                'job_security': int(request.form.get('priority_job_security', 3)),
                'learning_opportunities': int(request.form.get('priority_learning_opportunities', 3)),
                'team_environment': int(request.form.get('priority_team_environment', 3)),
                'work_autonomy': int(request.form.get('priority_work_autonomy', 3)),
                'benefits': int(request.form.get('priority_benefits', 3))
            }
            priorities_json = json.dumps(priorities)
            
            # Handle file upload
            if 'resume_file' in request.files:
                file = request.files['resume_file']
                if file and file.filename != '' and allowed_file(file.filename):
                    try:
                        filename = secure_filename(file.filename)
                        # Create unique filename with user ID
                        file_extension = filename.rsplit('.', 1)[1].lower()
                        unique_filename = f"resume_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{file_extension}"
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                        
                        # Save the file
                        file.save(file_path)
                        
                        # Extract text from the file
                        extracted_text = extract_text_from_file(file_path, filename)
                        
                        if extracted_text:
                            # If we extracted text successfully, use it as resume_text
                            # If user also provided manual text, combine them
                            if resume_text:
                                resume_text = f"=== UPLOADED RESUME ===\n{extracted_text}\n\n=== ADDITIONAL NOTES ===\n{resume_text}"
                            else:
                                resume_text = extracted_text
                            flash('Resume uploaded and processed successfully!', 'success')
                        else:
                            flash('Could not extract text from resume file. Please try again or enter text manually.', 'warning')
                            
                        # Clean up - optionally keep the file or delete it
                        # os.remove(file_path)  # Uncomment to delete file after processing
                        
                    except Exception as e:
                        print(f"Error processing resume file: {e}")
                        flash('Error processing resume file. Please try again.', 'error')
                elif file and file.filename != '' and not allowed_file(file.filename):
                    flash('Invalid file type. Please upload a PDF or DOCX file.', 'error')
            
            # Check if seeker profile already exists
            existing_seeker = conn.execute('SELECT id FROM job_seekers WHERE user_id = ?', (user_id,)).fetchone()

            if existing_seeker:
                # Update existing profile
                conn.execute('''
                    UPDATE job_seekers SET full_name = ?, resume_text = ?, personal_statement = ?, skills = ?,
                        experience_years = ?, education = ?, preferred_location = ?, salary_expectation = ?,
                        priorities = ?, preferred_employment_types = ?
                    WHERE user_id = ?
                ''', (full_name, resume_text, personal_statement, skills, experience_years, education,
                      preferred_location, salary_expectation, priorities_json, preferred_employment_types_json, user_id))
            else:
                conn.execute('''
                    INSERT INTO job_seekers 
                    (user_id, full_name, resume_text, personal_statement, skills, 
                     experience_years, education, preferred_location, salary_expectation, priorities, preferred_employment_types)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, full_name, resume_text, personal_statement, skills,
                      experience_years, education, preferred_location, salary_expectation, priorities_json, preferred_employment_types_json))
        
        elif user_type == 'company':
            company_name = request.form['company_name']
            description = request.form['description']
            industry = request.form['industry']
            size = request.form['size']
            location = request.form['location']
            website = request.form.get('website', '')
            
            # Check if company profile already exists
            existing_company = conn.execute('SELECT id FROM companies WHERE user_id = ?', (user_id,)).fetchone()

            if existing_company:
                conn.execute('''
                    UPDATE companies SET company_name = ?, description = ?, industry = ?, size = ?, location = ?, website = ?
                    WHERE user_id = ?
                ''', (company_name, description, industry, size, location, website, user_id))
            else:
                conn.execute('''
                    INSERT INTO companies 
                    (user_id, company_name, description, industry, size, location, website)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, company_name, description, industry, size, location, website))
        
        conn.commit()
        conn.close()
        
        flash('Profile setup completed!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('profile_setup.html', user_type=session.get('user_type'))

@app.route('/dashboard')
def dashboard():
    """User dashboard."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_type = session['user_type']
    conn = get_db_connection()
    
    if user_type == 'seeker':
        # Get seeker profile
        seeker = conn.execute(
            'SELECT * FROM job_seekers WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        # Get matches
        matches = conn.execute('''
            SELECT m.*, j.title, j.description, j.location, j.salary_range, c.company_name, c.user_id as company_user_id
            FROM matches m
            JOIN jobs j ON m.job_id = j.id
            JOIN companies c ON j.company_id = c.id
            WHERE m.job_seeker_id = ?
            ORDER BY m.match_score DESC, m.created_at DESC
            LIMIT 10
        ''', (seeker['id'] if seeker else 0,)).fetchall()
        
        # Get job offers
        job_offers = []
        if seeker:
            job_offers = conn.execute('''
                SELECT jo.*, j.title as job_title, j.description as job_description, 
                       j.location, j.salary_range, c.company_name, c.user_id as company_user_id
                FROM job_offers jo
                JOIN jobs j ON jo.job_id = j.id
                JOIN companies c ON jo.company_id = c.id
                WHERE jo.job_seeker_id = ?
                ORDER BY jo.offered_at DESC
            ''', (seeker['id'],)).fetchall()
        
        conn.close()
        return render_template('dashboard_seeker.html', seeker=seeker, matches=matches, job_offers=job_offers)
    
    elif user_type == 'company':
        # Get company profile
        company = conn.execute(
            'SELECT * FROM companies WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        # Get company jobs
        jobs = conn.execute(
            'SELECT * FROM jobs WHERE company_id = ? ORDER BY created_at DESC',
            (company['id'] if company else 0,)
        ).fetchall()
        
        # Get matched candidates for company's jobs
        matched_candidates = []
        if company:
            rows = conn.execute('''
                SELECT m.*, j.title as job_title, js.full_name, js.skills, js.experience_years, 
                       js.education, js.preferred_location, js.salary_expectation, js.user_id
                FROM matches m
                JOIN jobs j ON m.job_id = j.id
                JOIN job_seekers js ON m.job_seeker_id = js.id
                WHERE j.company_id = ?
                ORDER BY m.match_score DESC, m.created_at DESC
                LIMIT 50
            ''', (company['id'],)).fetchall()
            # Deduplicate by job_seeker_id keeping first (highest score)
            seen = set()
            for r in rows:
                if r['job_seeker_id'] in seen:
                    continue
                seen.add(r['job_seeker_id'])
                matched_candidates.append(r)
        
        conn.close()
        return render_template('dashboard_company.html', company=company, jobs=jobs, matched_candidates=matched_candidates)
    
    conn.close()
    return redirect(url_for('index'))

@app.route('/post-job', methods=['GET', 'POST'])
def post_job():
    """Post a new job (companies only)."""
    if 'user_id' not in session or session['user_type'] != 'company':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        conn = get_db_connection()
        company = conn.execute(
            'SELECT id FROM companies WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not company:
            flash('Please complete your company profile first.', 'error')
            conn.close()
            return redirect(url_for('profile_setup'))
        
        title = request.form['title']
        description = request.form['description']
        requirements = request.form['requirements']
        tags = request.form['tags']
        location = request.form['location']
        salary_range = request.form['salary_range']
        employment_type = request.form['employment_type']
        experience_required = int(request.form.get('experience_required', 0))
        
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO jobs 
            (company_id, title, description, requirements, tags, location, 
             salary_range, employment_type, experience_required)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (company['id'], title, description, requirements, tags, location,
              salary_range, employment_type, experience_required))
        
        job_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        flash('Job posted successfully!', 'success')
        
        # Trigger AI matching for this new job
        find_matches_for_job(job_id)
        
        return redirect(url_for('dashboard'))
    
    return render_template('post_job.html')

def find_matches_for_job(job_id):
    """Find and create matches for a specific job."""
    print(f"Finding matches for job ID: {job_id}")
    conn = get_db_connection()
    
    # Get job details
    job = conn.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    if not job:
        print(f"Job {job_id} not found!")
        conn.close()
        return
    
    print(f"Job found: {job['title']}")
    
    # Get all job seekers
    seekers = conn.execute('SELECT * FROM job_seekers').fetchall()
    print(f"Found {len(seekers)} job seekers")
    
    matches_created = 0
    for seeker in seekers:
        print(f"Processing seeker: {seeker['full_name']}")
        
        # Check if match already exists
        existing_match = conn.execute(
            'SELECT id FROM matches WHERE job_seeker_id = ? AND job_id = ?',
            (seeker['id'], job_id)
        ).fetchone()
        
        if existing_match:
            print(f"Match already exists for seeker {seeker['full_name']}")
            continue
        
        # Analyze match with AI
        print(f"Analyzing match with AI...")
        score, reasoning = analyze_match_with_ai(dict(seeker), dict(job))
        
        print(f"Score for {seeker['full_name']}: {score}%")
        
        # Only create match if score is above threshold (e.g., 60)
        if score >= 60:
            print(f"Creating match (score: {score}%)")
            conn.execute('''
                INSERT INTO matches (job_seeker_id, job_id, match_score, ai_reasoning)
                VALUES (?, ?, ?, ?)
            ''', (seeker['id'], job_id, score, reasoning))
            matches_created += 1
        else:
            print(f"Score too low ({score}%), not creating match")
    
    conn.commit()
    conn.close()
    print(f"Created {matches_created} new matches for job {job_id}")

@app.route('/api/test')
def test_api():
    """Simple test endpoint to verify API is working."""
    print("=== TEST API ENDPOINT HIT ===")
    return jsonify({'status': 'API is working', 'session_user': session.get('user_id', 'Not logged in')})

@app.route('/api/run-matching')
def run_matching():
    """API endpoint to run AI matching for all active jobs."""
    print(f"=== RUN MATCHING ENDPOINT HIT ===")
    print(f"Request method: {request.method}")
    print(f"Session contents: {dict(session)}")
    print(f"User ID in session: {session.get('user_id', 'NOT FOUND')}")
    
    if 'user_id' not in session:
        print("ERROR: User not authenticated - no user_id in session")
        return jsonify({'error': 'Not authenticated'}), 401
    
    print(f"Running matching for user: {session['user_id']}")
    
    conn = get_db_connection()
    
    # Check user type to determine matching strategy
    user_type = session.get('user_type', 'seeker')
    
    if user_type == 'company':
        # Company-initiated matching: find candidates for their jobs
        company = conn.execute(
            'SELECT id FROM companies WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not company:
            conn.close()
            return jsonify({'error': 'Company profile not found'}), 404
        
        # Get company's active jobs
        jobs = conn.execute(
            'SELECT id FROM jobs WHERE company_id = ? AND is_active = 1',
            (company['id'],)
        ).fetchall()
        print(f"Found {len(jobs)} active jobs for company")
        
        matches_created = 0
        for job in jobs:
            print(f"Processing job ID: {job['id']}")
            find_matches_for_job(job['id'])
            matches_created += 1
            
        conn.close()
        return jsonify({
            'success': True,
            'message': f'Candidate matching completed for {matches_created} jobs',
            'jobs_processed': matches_created
        })
    
    else:
        # Job seeker-initiated matching: find jobs for all seekers (original behavior)
        # Get all active jobs
        jobs = conn.execute('SELECT id FROM jobs WHERE is_active = 1').fetchall()
        print(f"Found {len(jobs)} active jobs")
        
        matches_created = 0
        for job in jobs:
            print(f"Processing job ID: {job['id']}")
            find_matches_for_job(job['id'])
            matches_created += 1
        
        conn.close()
        
        print(f"Matching completed. Processed {matches_created} jobs")
        
        return jsonify({
            'success': True,
            'message': f'Matching completed for {matches_created} jobs',
            'jobs_processed': matches_created
        })

@app.route('/advice')
def advice():
    """Career advice and guidance page."""
    return render_template('advice.html')

@app.route('/api/get-advice', methods=['POST'])
def get_advice():
    """API endpoint to get AI-powered career advice."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        data = request.get_json()
        question = data.get('question', '')
        category = data.get('category', 'general')
        
        if not question:
            return jsonify({'error': 'Question is required'}), 400
        
        # Get user profile for personalized advice
        conn = get_db_connection()
        user_type = session.get('user_type', 'seeker')
        user_profile = {}
        
        if user_type == 'seeker':
            seeker = conn.execute(
                'SELECT * FROM job_seekers WHERE user_id = ?',
                (session['user_id'],)
            ).fetchone()
            if seeker:
                user_profile = dict(seeker)
        elif user_type == 'company':
            company = conn.execute(
                'SELECT * FROM companies WHERE user_id = ?',
                (session['user_id'],)
            ).fetchone()
            if company:
                user_profile = dict(company)
        
        conn.close()
        
        # Generate AI advice
        advice_response = generate_ai_advice(question, category, user_type, user_profile)
        
        return jsonify({
            'success': True,
            'advice': advice_response
        })
        
    except Exception as e:
        print(f"Error generating advice: {e}")
        return jsonify({'error': 'Failed to generate advice'}), 500

@app.route('/update-priorities', methods=['GET', 'POST'])
def update_priorities():
    """Update job seeker priorities."""
    if 'user_id' not in session or session['user_type'] != 'seeker':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    seeker = conn.execute(
        'SELECT * FROM job_seekers WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not seeker:
        flash('Please complete your profile first.', 'error')
        conn.close()
        return redirect(url_for('profile_setup'))
    
    if request.method == 'POST':
        # Handle priorities update
        priorities = {
            'salary': int(request.form.get('priority_salary', 3)),
            'work_life_balance': int(request.form.get('priority_work_life_balance', 3)),
            'remote_work': int(request.form.get('priority_remote_work', 3)),
            'company_culture': int(request.form.get('priority_company_culture', 3)),
            'career_growth': int(request.form.get('priority_career_growth', 3)),
            'job_security': int(request.form.get('priority_job_security', 3)),
            'learning_opportunities': int(request.form.get('priority_learning_opportunities', 3)),
            'team_environment': int(request.form.get('priority_team_environment', 3)),
            'work_autonomy': int(request.form.get('priority_work_autonomy', 3)),
            'benefits': int(request.form.get('priority_benefits', 3))
        }
        priorities_json = json.dumps(priorities)
        
        # Handle preferred employment types
        preferred_employment_types = request.form.getlist('preferred_employment_types')
        if not preferred_employment_types:
            preferred_employment_types = ['Full-time']
        preferred_employment_types_json = json.dumps(preferred_employment_types)
        
        conn.execute(
            'UPDATE job_seekers SET priorities = ?, preferred_employment_types = ? WHERE user_id = ?',
            (priorities_json, preferred_employment_types_json, session['user_id'])
        )
        conn.commit()
        conn.close()
        
        flash('Priorities and employment preferences updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    # Parse current priorities and employment types for display
    current_priorities = {}
    current_employment_types = []
    try:
        current_priorities = json.loads(seeker['priorities'] or '{}')
        current_employment_types = json.loads(seeker.get('preferred_employment_types', '["Full-time"]'))
    except:
        current_priorities = {}
        current_employment_types = ['Full-time']
    
    conn.close()
    return render_template('update_priorities.html', 
                         priorities=current_priorities, 
                         preferred_employment_types=current_employment_types)

@app.route('/job/<int:job_id>')
def view_job(job_id):
    """View detailed job information."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get job details with company info
    job = conn.execute('''
        SELECT j.*, c.company_name, c.description as company_description, 
               c.industry, c.size, c.website, c.user_id as company_user_id
        FROM jobs j
        JOIN companies c ON j.company_id = c.id
        WHERE j.id = ?
    ''', (job_id,)).fetchone()
    
    if not job:
        flash('Job not found.', 'error')
        conn.close()
        return redirect(url_for('dashboard'))
    
    # Check if job is saved (for job seekers)
    is_saved = False
    if session.get('user_type') == 'seeker':
        seeker = conn.execute(
            'SELECT id FROM job_seekers WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if seeker:
            saved = conn.execute(
                'SELECT id FROM saved_jobs WHERE job_seeker_id = ? AND job_id = ?',
                (seeker['id'], job_id)
            ).fetchone()
            is_saved = bool(saved)
    
    conn.close()
    return render_template('job_details.html', job=job, is_saved=is_saved)

@app.route('/candidate/<int:candidate_id>')
def view_candidate(candidate_id):
    """View detailed candidate profile."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get candidate details
    candidate = conn.execute('''
        SELECT js.*, u.username, u.email
        FROM job_seekers js
        JOIN users u ON js.user_id = u.id
        WHERE js.id = ?
    ''', (candidate_id,)).fetchone()
    
    if not candidate:
        flash('Candidate not found.', 'error')
        conn.close()
        return redirect(url_for('dashboard'))
    
    # Check if candidate is saved (for companies)
    is_saved = False
    if session.get('user_type') == 'company':
        company = conn.execute(
            'SELECT id FROM companies WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if company:
            saved = conn.execute(
                'SELECT id FROM saved_candidates WHERE company_id = ? AND job_seeker_id = ?',
                (company['id'], candidate_id)
            ).fetchone()
            is_saved = bool(saved)
    
    conn.close()
    return render_template('candidate_profile.html', candidate=candidate, is_saved=is_saved)

@app.route('/edit-job/<int:job_id>', methods=['GET', 'POST'])
def edit_job(job_id):
    """Edit job posting."""
    if 'user_id' not in session or session['user_type'] != 'company':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Verify job ownership
    company = conn.execute(
        'SELECT id FROM companies WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not company:
        flash('Company profile not found.', 'error')
        conn.close()
        return redirect(url_for('dashboard'))
    
    job = conn.execute(
        'SELECT * FROM jobs WHERE id = ? AND company_id = ?',
        (job_id, company['id'])
    ).fetchone()
    
    if not job:
        flash('Job not found or access denied.', 'error')
        conn.close()
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        requirements = request.form['requirements']
        tags = request.form['tags']
        location = request.form['location']
        salary_range = request.form['salary_range']
        employment_type = request.form['employment_type']
        experience_required = int(request.form.get('experience_required', 0))
        is_active = bool(request.form.get('is_active'))
        
        conn.execute('''
            UPDATE jobs SET 
            title = ?, description = ?, requirements = ?, tags = ?, 
            location = ?, salary_range = ?, employment_type = ?, 
            experience_required = ?, is_active = ?
            WHERE id = ?
        ''', (title, description, requirements, tags, location, 
              salary_range, employment_type, experience_required, 
              is_active, job_id))
        
        conn.commit()
        conn.close()
        
        flash('Job updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    conn.close()
    return render_template('edit_job.html', job=job)

@app.route('/api/save-job/<int:job_id>', methods=['POST'])
def save_job(job_id):
    """Save/unsave a job for job seeker."""
    if 'user_id' not in session or session['user_type'] != 'seeker':
        return jsonify({'error': 'Not authorized'}), 401
    
    conn = get_db_connection()
    
    seeker = conn.execute(
        'SELECT id FROM job_seekers WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not seeker:
        conn.close()
        return jsonify({'error': 'Profile not found'}), 404
    
    # Check if already saved
    saved = conn.execute(
        'SELECT id FROM saved_jobs WHERE job_seeker_id = ? AND job_id = ?',
        (seeker['id'], job_id)
    ).fetchone()
    
    if saved:
        # Unsave
        conn.execute(
            'DELETE FROM saved_jobs WHERE job_seeker_id = ? AND job_id = ?',
            (seeker['id'], job_id)
        )
        action = 'unsaved'
    else:
        # Save
        conn.execute(
            'INSERT INTO saved_jobs (job_seeker_id, job_id) VALUES (?, ?)',
            (seeker['id'], job_id)
        )
        action = 'saved'
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'action': action})

@app.route('/api/save-candidate/<int:candidate_id>', methods=['POST'])
def save_candidate(candidate_id):
    """Save/unsave a candidate for company."""
    if 'user_id' not in session or session['user_type'] != 'company':
        return jsonify({'error': 'Not authorized'}), 401
    
    conn = get_db_connection()
    
    company = conn.execute(
        'SELECT id FROM companies WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not company:
        conn.close()
        return jsonify({'error': 'Profile not found'}), 404
    
    # Check if already saved
    saved = conn.execute(
        'SELECT id FROM saved_candidates WHERE company_id = ? AND job_seeker_id = ?',
        (company['id'], candidate_id)
    ).fetchone()
    
    if saved:
        # Unsave
        conn.execute(
            'DELETE FROM saved_candidates WHERE company_id = ? AND job_seeker_id = ?',
            (company['id'], candidate_id)
        )
        action = 'unsaved'
    else:
        # Save
        conn.execute(
            'INSERT INTO saved_candidates (company_id, job_seeker_id) VALUES (?, ?)',
            (company['id'], candidate_id)
        )
        action = 'saved'
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'action': action})

@app.route('/api/apply-job/<int:job_id>', methods=['POST'])
def apply_job(job_id):
    """Apply for a job."""
    if 'user_id' not in session or session['user_type'] != 'seeker':
        return jsonify({'error': 'Not authorized'}), 401
    
    conn = get_db_connection()
    
    # Get job seeker profile
    seeker = conn.execute(
        'SELECT id FROM job_seekers WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not seeker:
        conn.close()
        return jsonify({'error': 'Profile not found'}), 404
    
    # Check if job exists and is active
    job = conn.execute(
        'SELECT id, title FROM jobs WHERE id = ? AND is_active = 1',
        (job_id,)
    ).fetchone()
    
    if not job:
        conn.close()
        return jsonify({'error': 'Job not found or no longer active'}), 404
    
    # Check if already applied
    existing_application = conn.execute(
        'SELECT id FROM applications WHERE job_seeker_id = ? AND job_id = ?',
        (seeker['id'], job_id)
    ).fetchone()
    
    if existing_application:
        conn.close()
        return jsonify({'error': 'You have already applied for this job'}), 400
    
    # Get cover letter from request
    data = request.get_json()
    cover_letter = data.get('cover_letter', '') if data else ''
    
    # Create application
    conn.execute('''
        INSERT INTO applications (job_seeker_id, job_id, cover_letter)
        VALUES (?, ?, ?)
    ''', (seeker['id'], job_id, cover_letter))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Application submitted successfully!'})

@app.route('/api/check-application/<int:job_id>')
def check_application(job_id):
    """Check if user has already applied to a job."""
    if 'user_id' not in session or session['user_type'] != 'seeker':
        return jsonify({'error': 'Not authorized'}), 401
    
    conn = get_db_connection()
    
    seeker = conn.execute(
        'SELECT id FROM job_seekers WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not seeker:
        conn.close()
        return jsonify({'has_applied': False})
    
    application = conn.execute(
        'SELECT id, status, applied_at FROM applications WHERE job_seeker_id = ? AND job_id = ?',
        (seeker['id'], job_id)
    ).fetchone()
    
    conn.close()
    
    if application:
        return jsonify({
            'has_applied': True,
            'status': application['status'],
            'applied_at': application['applied_at']
        })
    else:
        return jsonify({'has_applied': False})

@app.route('/applications')
def applications():
    """View applications (for both job seekers and companies)."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    user_type = session['user_type']
    
    if user_type == 'seeker':
        # Get seeker's applications
        seeker = conn.execute(
            'SELECT id FROM job_seekers WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not seeker:
            flash('Please complete your profile first.', 'error')
            conn.close()
            return redirect(url_for('profile_setup'))
        
        applications = conn.execute('''
            SELECT a.*, j.title, j.location, j.salary_range, j.employment_type,
                   c.company_name, c.id as company_id
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            JOIN companies c ON j.company_id = c.id
            WHERE a.job_seeker_id = ?
            ORDER BY a.applied_at DESC
        ''', (seeker['id'],)).fetchall()
        
        conn.close()
        return render_template('applications_seeker.html', applications=applications)
    
    elif user_type == 'company':
        # Get applications for company's jobs
        company = conn.execute(
            'SELECT id FROM companies WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not company:
            flash('Please complete your profile first.', 'error')
            conn.close()
            return redirect(url_for('profile_setup'))
        
        applications = conn.execute('''
            SELECT a.*, j.title as job_title, j.id as job_id,
                   js.full_name, js.skills, js.experience_years, 
                   js.education, js.user_id as seeker_user_id
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            JOIN job_seekers js ON a.job_seeker_id = js.id
            WHERE j.company_id = ?
            ORDER BY a.applied_at DESC
        ''', (company['id'],)).fetchall()
        
        conn.close()
        return render_template('applications_company.html', applications=applications)
    
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/offers')
def offers():
    """View job offers (for both job seekers and companies)."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    user_type = session['user_type']
    
    if user_type == 'seeker':
        # Get seeker's job offers
        seeker = conn.execute(
            'SELECT id FROM job_seekers WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not seeker:
            flash('Please complete your profile first.', 'error')
            conn.close()
            return redirect(url_for('profile_setup'))
        
        offers = conn.execute('''
            SELECT jo.*, j.title as job_title, j.description as job_description, 
                   j.location, j.salary_range, c.company_name, c.user_id as company_user_id
            FROM job_offers jo
            JOIN jobs j ON jo.job_id = j.id
            JOIN companies c ON jo.company_id = c.id
            WHERE jo.job_seeker_id = ?
            ORDER BY jo.offered_at DESC
        ''', (seeker['id'],)).fetchall()
        
        conn.close()
        return render_template('offers_seeker.html', offers=offers)
    
    elif user_type == 'company':
        # Get company's sent job offers
        company = conn.execute(
            'SELECT id FROM companies WHERE user_id = ?',
            (session['user_id'],)
        ).fetchone()
        
        if not company:
            flash('Please complete your profile first.', 'error')
            conn.close()
            return redirect(url_for('profile_setup'))
        
        offers = conn.execute('''
            SELECT jo.*, j.title as job_title, j.id as job_id,
                   js.full_name, js.skills, js.experience_years, 
                   js.user_id as seeker_user_id
            FROM job_offers jo
            JOIN jobs j ON jo.job_id = j.id
            JOIN job_seekers js ON jo.job_seeker_id = js.id
            WHERE jo.company_id = ?
            ORDER BY jo.offered_at DESC
        ''', (company['id'],)).fetchall()
        
        conn.close()
        return render_template('offers_company.html', offers=offers)
    
    conn.close()
    return redirect(url_for('dashboard'))

@app.route('/contact/<int:user_id>', methods=['GET', 'POST'])
def contact_user(user_id):
    """Send message to another user."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if session['user_id'] == user_id:
        flash('You cannot send a message to yourself.', 'error')
        return redirect(url_for('dashboard'))
    
    conn = get_db_connection()
    
    # Get recipient info
    recipient = conn.execute(
        'SELECT username, user_type FROM users WHERE id = ?',
        (user_id,)
    ).fetchone()
    
    if not recipient:
        flash('User not found.', 'error')
        conn.close()
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        subject = request.form['subject']
        message = request.form['message']
        
        if not subject or not message:
            flash('Please fill in all fields.', 'error')
        else:
            conn.execute('''
                INSERT INTO messages (sender_id, receiver_id, subject, message)
                VALUES (?, ?, ?, ?)
            ''', (session['user_id'], user_id, subject, message))
            
            conn.commit()
            flash('Message sent successfully!', 'success')
            conn.close()
            return redirect(url_for('dashboard'))
    
    conn.close()
    return render_template('contact_user.html', recipient=recipient, recipient_id=user_id)

@app.route('/api/get-company-user/<int:company_id>')
def get_company_user(company_id):
    """Get user ID for a company."""
    conn = get_db_connection()
    
    company = conn.execute(
        'SELECT user_id FROM companies WHERE id = ?',
        (company_id,)
    ).fetchone()
    
    conn.close()
    
    if company:
        return jsonify({'success': True, 'user_id': company['user_id']})
    else:
        return jsonify({'success': False, 'error': 'Company not found'}), 404

@app.route('/api/get-company-jobs')
def get_company_jobs():
    """Get active jobs for the current company."""
    if 'user_id' not in session or session['user_type'] != 'company':
        return jsonify({'error': 'Not authorized'}), 401
    
    conn = get_db_connection()
    
    # Get company profile
    company = conn.execute(
        'SELECT id FROM companies WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not company:
        conn.close()
        return jsonify({'error': 'Company profile not found'}), 404
    
    # Get company's active jobs
    jobs = conn.execute(
        'SELECT id, title, location, salary_range FROM jobs WHERE company_id = ? AND is_active = 1 ORDER BY created_at DESC',
        (company['id'],)
    ).fetchall()
    
    conn.close()
    
    jobs_list = [dict(job) for job in jobs]
    return jsonify({'success': True, 'jobs': jobs_list})

@app.route('/api/offer-job/<int:job_seeker_id>/<int:job_id>', methods=['POST'])
def offer_job(job_seeker_id, job_id):
    """Offer a job to a candidate."""
    if 'user_id' not in session or session['user_type'] != 'company':
        return jsonify({'error': 'Not authorized'}), 401
    
    conn = get_db_connection()
    
    # Get company profile
    company = conn.execute(
        'SELECT id FROM companies WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not company:
        conn.close()
        return jsonify({'error': 'Company profile not found'}), 404
    
    # Verify the job belongs to this company
    job = conn.execute(
        'SELECT id, title FROM jobs WHERE id = ? AND company_id = ?',
        (job_id, company['id'])
    ).fetchone()
    
    if not job:
        conn.close()
        return jsonify({'error': 'Job not found or access denied'}), 404
    
    # Check if job seeker exists
    seeker = conn.execute(
        'SELECT id, full_name FROM job_seekers WHERE id = ?',
        (job_seeker_id,)
    ).fetchone()
    
    if not seeker:
        conn.close()
        return jsonify({'error': 'Job seeker not found'}), 404
    
    # Check if offer already exists
    existing_offer = conn.execute(
        'SELECT id FROM job_offers WHERE job_id = ? AND job_seeker_id = ?',
        (job_id, job_seeker_id)
    ).fetchone()
    
    if existing_offer:
        conn.close()
        return jsonify({'error': 'Job offer already exists for this candidate'}), 400
    
    # Get offer details from request
    data = request.get_json()
    offer_message = data.get('offer_message', '') if data else ''
    salary_offered = data.get('salary_offered', '') if data else ''
    start_date = data.get('start_date', '') if data else ''
    
    # Create job offer
    conn.execute('''
        INSERT INTO job_offers (job_id, job_seeker_id, company_id, offer_message, salary_offered, start_date)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (job_id, job_seeker_id, company['id'], offer_message, salary_offered, start_date))
    
    # Update application status if an application exists
    conn.execute('''
        UPDATE applications 
        SET status = 'offered' 
        WHERE job_seeker_id = ? AND job_id = ? AND status = 'pending'
    ''', (job_seeker_id, job_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Job offer sent successfully!'})

@app.route('/api/respond-offer/<int:offer_id>', methods=['POST'])
def respond_offer(offer_id):
    """Accept or decline a job offer."""
    if 'user_id' not in session or session['user_type'] != 'seeker':
        return jsonify({'error': 'Not authorized'}), 401
    
    conn = get_db_connection()
    
    # Get job seeker profile
    seeker = conn.execute(
        'SELECT id FROM job_seekers WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not seeker:
        conn.close()
        return jsonify({'error': 'Profile not found'}), 404
    
    # Get the offer and verify it belongs to this seeker
    offer = conn.execute('''
        SELECT jo.*, j.title as job_title, c.company_name
        FROM job_offers jo
        JOIN jobs j ON jo.job_id = j.id
        JOIN companies c ON jo.company_id = c.id
        WHERE jo.id = ? AND jo.job_seeker_id = ?
    ''', (offer_id, seeker['id'])).fetchone()
    
    if not offer:
        conn.close()
        return jsonify({'error': 'Job offer not found or access denied'}), 404
    
    if offer['status'] != 'pending':
        conn.close()
        return jsonify({'error': 'This offer has already been responded to'}), 400
    
    # Get response from request
    data = request.get_json()
    response = data.get('response', '') if data else ''  # 'accepted' or 'declined'
    notes = data.get('notes', '') if data else ''
    
    if response not in ['accepted', 'declined']:
        conn.close()
        return jsonify({'error': 'Invalid response. Must be "accepted" or "declined"'}), 400
    
    # Update offer status
    conn.execute('''
        UPDATE job_offers 
        SET status = ?, responded_at = CURRENT_TIMESTAMP, notes = ?
        WHERE id = ?
    ''', (response, notes, offer_id))
    
    conn.commit()
    conn.close()
    
    action = 'accepted' if response == 'accepted' else 'declined'
    return jsonify({'success': True, 'message': f'Job offer {action} successfully!'})

@app.route('/api/withdraw-offer/<int:offer_id>', methods=['POST'])
def withdraw_offer(offer_id):
    """Withdraw a job offer."""
    if 'user_id' not in session or session['user_type'] != 'company':
        return jsonify({'error': 'Not authorized'}), 401
    
    conn = get_db_connection()
    
    # Get company profile
    company = conn.execute(
        'SELECT id FROM companies WHERE user_id = ?',
        (session['user_id'],)
    ).fetchone()
    
    if not company:
        conn.close()
        return jsonify({'error': 'Company profile not found'}), 404
    
    # Get the offer and verify it belongs to this company
    offer = conn.execute(
        'SELECT * FROM job_offers WHERE id = ? AND company_id = ?',
        (offer_id, company['id'])
    ).fetchone()
    
    if not offer:
        conn.close()
        return jsonify({'error': 'Job offer not found or access denied'}), 404
    
    if offer['status'] != 'pending':
        conn.close()
        return jsonify({'error': 'Only pending offers can be withdrawn'}), 400
    
    # Update offer status to withdrawn
    conn.execute(
        'UPDATE job_offers SET status = "withdrawn" WHERE id = ?',
        (offer_id,)
    )
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Job offer withdrawn successfully!'})

def generate_ai_advice(question, category, user_type, user_profile):
    """Generate AI-powered career advice."""
    try:
        # Create context based on user profile
        context = f"User type: {user_type}\n"
        if user_type == 'seeker' and user_profile:
            context += f"Experience: {user_profile.get('experience_years', 0)} years\n"
            context += f"Skills: {user_profile.get('skills', 'N/A')}\n"
            context += f"Education: {user_profile.get('education', 'N/A')}\n"
            context += f"Location preference: {user_profile.get('preferred_location', 'N/A')}\n"
        elif user_type == 'company' and user_profile:
            context += f"Industry: {user_profile.get('industry', 'N/A')}\n"
            context += f"Company size: {user_profile.get('size', 'N/A')}\n"
        
        prompt = f"""
        You are a career advisor and HR expert. Provide helpful, actionable career advice.
        
        Category: {category}
        User Context: {context}
        
        Question: {question}
        
        Please provide practical, specific advice that is:
        1. Actionable and specific
        2. Relevant to their background and experience level
        3. Industry-aware and current
        4. Encouraging but realistic
        5. Include specific steps they can take
        
        Keep your response concise but comprehensive (2-4 paragraphs).
        """
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert career advisor with deep knowledge of job markets, career development, and professional growth."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=600
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        print(f"AI Advice Error: {e}")
        return "I'm sorry, I'm having trouble generating advice right now. Please try again later or contact our support team for assistance."

@app.route('/api/jobs/filter')
def filter_jobs():
    """Filter jobs by employment type and other criteria."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    employment_type = request.args.get('employment_type')
    location = request.args.get('location')
    min_salary = request.args.get('min_salary', type=int)
    max_salary = request.args.get('max_salary', type=int)
    
    conn = get_db_connection()
    
    # Build dynamic query
    query = '''
        SELECT j.*, c.company_name 
        FROM jobs j 
        JOIN companies c ON j.company_id = c.id 
        WHERE j.is_active = 1
    '''
    params = []
    
    if employment_type and employment_type != 'all':
        query += ' AND j.employment_type = ?'
        params.append(employment_type)
    
    if location:
        query += ' AND (j.location LIKE ? OR j.location LIKE ?)'
        params.extend([f'%{location}%', '%Remote%'])
    
    # Simple salary filtering (assumes salary_range format like "$50,000 - $70,000")
    if min_salary or max_salary:
        query += ' AND j.salary_range IS NOT NULL AND j.salary_range != ""'
    
    query += ' ORDER BY j.created_at DESC LIMIT 50'
    
    jobs = conn.execute(query, params).fetchall()
    conn.close()
    
    # Convert to list of dictionaries
    jobs_list = []
    for job in jobs:
        job_dict = dict(job)
        
        # Simple salary extraction for filtering
        if min_salary or max_salary:
            salary_range = job_dict.get('salary_range', '')
            # Try to extract numeric values from salary range
            numbers = re.findall(r'\d+', salary_range.replace(',', ''))
            if len(numbers) >= 2:
                try:
                    job_min = int(numbers[0])
                    job_max = int(numbers[1])
                    if min_salary and job_max < min_salary:
                        continue
                    if max_salary and job_min > max_salary:
                        continue
                except:
                    pass
        
        jobs_list.append(job_dict)
    
    return jsonify({'success': True, 'jobs': jobs_list})

@app.route('/manifest.json')
def manifest():
    """Serve the PWA manifest file."""
    return send_from_directory('static', 'manifest.json')

@app.route('/service-worker.js')
def service_worker():
    """Serve the PWA service worker."""
    return send_from_directory(os.path.join('static', 'js'), 'service-worker.js')

@app.route('/api/rate/<int:target_user_id>', methods=['POST'])
def rate_user(target_user_id):
    """Rate another user (1-5 stars with optional review)."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    if session['user_id'] == target_user_id:
        return jsonify({'error': 'You cannot rate yourself'}), 400

    data = request.get_json() or {}
    rating_val = int(data.get('rating', 0))
    review = data.get('review', '').strip()

    if rating_val < 1 or rating_val > 5:
        return jsonify({'error': 'Rating must be between 1 and 5'}), 400

    conn = get_db_connection()
    # Validate target user exists
    target_user = conn.execute('SELECT id, user_type FROM users WHERE id = ?', (target_user_id,)).fetchone()
    if not target_user:
        conn.close()
        return jsonify({'error': 'Target user not found'}), 404

    # Only allow seeker -> company and company -> seeker ratings
    if session['user_type'] == 'seeker' and target_user['user_type'] != 'company':
        conn.close()
        return jsonify({'error': 'Job seekers can only rate companies'}), 400
    if session['user_type'] == 'company' and target_user['user_type'] != 'seeker':
        conn.close()
        return jsonify({'error': 'Companies can only rate job seekers'}), 400

    # Upsert rating
    conn.execute('''
        INSERT INTO ratings (rater_id, target_id, rating, review)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(rater_id, target_id) DO UPDATE SET rating = excluded.rating, review = excluded.review, created_at = CURRENT_TIMESTAMP
    ''', (session['user_id'], target_user_id, rating_val, review))
    conn.commit()

    # Calculate new average
    avg_row = conn.execute('SELECT ROUND(AVG(rating),1) as avg_rating, COUNT(*) as count FROM ratings WHERE target_id = ?', (target_user_id,)).fetchone()
    conn.close()

    return jsonify({'success': True, 'avg_rating': avg_row['avg_rating'], 'count': avg_row['count']})

@app.route('/api/get-ratings/<int:target_user_id>')
def get_ratings(target_user_id):
    """Get average rating, count, and individual reviews for a user."""
    conn = get_db_connection()
    
    # Get average and count
    stats = conn.execute('SELECT ROUND(AVG(rating),1) as avg_rating, COUNT(*) as count FROM ratings WHERE target_id = ?', (target_user_id,)).fetchone()
    
    # Get individual reviews with rater info
    reviews = conn.execute('''
        SELECT r.rating, r.review, r.created_at, u.username, u.user_type
        FROM ratings r
        JOIN users u ON r.rater_id = u.id
        WHERE r.target_id = ?
        ORDER BY r.created_at DESC
        LIMIT 10
    ''', (target_user_id,)).fetchall()
    
    conn.close()
    
    avg = stats['avg_rating'] if stats['avg_rating'] is not None else 0
    reviews_list = []
    for review in reviews:
        # Anonymize company reviewers, show job seeker names
        if review['user_type'] == 'company':
            display_name = 'Anonymous Company'
        else:
            display_name = review['username']
            
        reviews_list.append({
            'rating': review['rating'],
            'review': review['review'],
            'created_at': review['created_at'],
            'username': display_name,
            'user_type': review['user_type']
        })
    
    return jsonify({
        'avg_rating': avg, 
        'count': stats['count'],
        'reviews': reviews_list
    })

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000) 