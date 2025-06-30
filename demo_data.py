#!/usr/bin/env python3
"""
Demo Data Setup Script for Werkly
This script populates the database with sample users, companies, job seekers, and jobs for testing.
"""

import sqlite3
from werkzeug.security import generate_password_hash

def create_demo_data():
    """Create demo data for testing the application."""
    
    # Initialize database connection
    conn = sqlite3.connect('jobmatch.db')
    cursor = conn.cursor()
    
    print("Creating demo data...")
    
    # Demo users
    demo_users = [
        ('john_seeker', 'john@example.com', 'password123', 'seeker'),
        ('jane_dev', 'jane@example.com', 'password123', 'seeker'),
        ('mike_designer', 'mike@example.com', 'password123', 'seeker'),
        ('techcorp', 'hr@techcorp.com', 'password123', 'company'),
        ('startup_inc', 'jobs@startup.com', 'password123', 'company'),
        ('design_agency', 'talent@agency.com', 'password123', 'company'),
    ]
    
    # Insert demo users
    for username, email, password, user_type in demo_users:
        password_hash = generate_password_hash(password)
        try:
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, user_type)
                VALUES (?, ?, ?, ?)
            ''', (username, email, password_hash, user_type))
        except sqlite3.IntegrityError:
            print(f"User {username} already exists, skipping...")
    
    conn.commit()
    
    # Get user IDs
    user_map = {}
    for username, _, _, _ in demo_users:
        cursor.execute('SELECT id, user_type FROM users WHERE username = ?', (username,))
        result = cursor.fetchone()
        if result:
            user_map[username] = {'id': result[0], 'type': result[1]}
    
    # Demo job seekers
    demo_seekers = [
        {
            'username': 'john_seeker',
            'full_name': 'John Smith',
            'resume_text': 'Experienced software engineer with 5 years in full-stack development. Proficient in Python, JavaScript, React, and Node.js. Led multiple projects from conception to deployment.',
            'personal_statement': 'Passionate software engineer looking for challenging opportunities in web development. I love solving complex problems and building scalable applications.',
            'skills': 'Python, JavaScript, React, Node.js, MongoDB, PostgreSQL, AWS, Docker',
            'experience_years': 5,
            'education': 'Bachelor of Science in Computer Science, MIT',
            'preferred_location': 'San Francisco, CA',
            'salary_expectation': 120000
        },
        {
            'username': 'jane_dev',
            'full_name': 'Jane Johnson',
            'resume_text': 'Senior frontend developer with expertise in React, Vue.js, and modern CSS frameworks. 7 years of experience building responsive web applications.',
            'personal_statement': 'Creative frontend developer who enjoys creating beautiful and intuitive user interfaces. Always staying up-to-date with the latest web technologies.',
            'skills': 'React, Vue.js, TypeScript, CSS3, HTML5, Webpack, Jest, Figma',
            'experience_years': 7,
            'education': 'Master in Web Development, Stanford University',
            'preferred_location': 'Remote',
            'salary_expectation': 140000
        },
        {
            'username': 'mike_designer',
            'full_name': 'Mike Wilson',
            'resume_text': 'UX/UI Designer with 4 years of experience creating user-centered designs for web and mobile applications. Strong background in user research and prototyping.',
            'personal_statement': 'Design-thinking enthusiast who believes great design can change the world. I focus on creating meaningful user experiences that solve real problems.',
            'skills': 'Figma, Sketch, Adobe Creative Suite, Prototyping, User Research, Wireframing',
            'experience_years': 4,
            'education': 'Bachelor of Fine Arts in Graphic Design, RISD',
            'preferred_location': 'New York, NY',
            'salary_expectation': 95000
        }
    ]
    
    # Insert demo job seekers
    for seeker in demo_seekers:
        if seeker['username'] in user_map:
            user_id = user_map[seeker['username']]['id']
            try:
                cursor.execute('''
                    INSERT INTO job_seekers 
                    (user_id, full_name, resume_text, personal_statement, skills, 
                     experience_years, education, preferred_location, salary_expectation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, seeker['full_name'], seeker['resume_text'], 
                      seeker['personal_statement'], seeker['skills'], 
                      seeker['experience_years'], seeker['education'], 
                      seeker['preferred_location'], seeker['salary_expectation']))
            except sqlite3.IntegrityError:
                print(f"Job seeker {seeker['username']} already exists, skipping...")
    
    conn.commit()
    
    # Demo companies
    demo_companies = [
        {
            'username': 'techcorp',
            'company_name': 'TechCorp Solutions',
            'description': 'Leading technology company specializing in cloud solutions and enterprise software. We foster innovation and offer great benefits to our employees.',
            'industry': 'Technology',
            'size': '201-1000',
            'location': 'San Francisco, CA',
            'website': 'https://techcorp.com'
        },
        {
            'username': 'startup_inc',
            'company_name': 'Startup Inc',
            'description': 'Fast-growing startup revolutionizing the fintech space. Join our small but mighty team and help shape the future of finance.',
            'industry': 'Finance',
            'size': '11-50',
            'location': 'Austin, TX',
            'website': 'https://startup-inc.com'
        },
        {
            'username': 'design_agency',
            'company_name': 'Creative Design Agency',
            'description': 'Award-winning design agency working with top brands worldwide. We value creativity, collaboration, and cutting-edge design.',
            'industry': 'Media',
            'size': '51-200',
            'location': 'New York, NY',
            'website': 'https://creativeagency.com'
        }
    ]
    
    # Insert demo companies
    for company in demo_companies:
        if company['username'] in user_map:
            user_id = user_map[company['username']]['id']
            try:
                cursor.execute('''
                    INSERT INTO companies 
                    (user_id, company_name, description, industry, size, location, website)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, company['company_name'], company['description'], 
                      company['industry'], company['size'], company['location'], 
                      company['website']))
            except sqlite3.IntegrityError:
                print(f"Company {company['username']} already exists, skipping...")
    
    conn.commit()
    
    # Get company IDs
    company_map = {}
    cursor.execute('SELECT id, user_id FROM companies')
    companies = cursor.fetchall()
    for comp_id, user_id in companies:
        for username, user_info in user_map.items():
            if user_info['id'] == user_id:
                company_map[username] = comp_id
                break
    
    # Demo jobs
    demo_jobs = [
        {
            'company_username': 'techcorp',
            'title': 'Senior Full Stack Developer',
            'description': 'We are looking for a Senior Full Stack Developer to join our growing engineering team. You will work on cutting-edge projects using modern technologies and help architect scalable solutions for our enterprise clients.',
            'requirements': 'Bachelor\'s degree in Computer Science or related field. 5+ years of experience with Python, JavaScript, and React. Experience with cloud platforms (AWS/Azure). Strong problem-solving skills and ability to work in a team environment.',
            'tags': 'Python, JavaScript, React, AWS, Full Stack, Senior',
            'location': 'San Francisco, CA',
            'salary_range': '$120,000 - $160,000',
            'employment_type': 'Full-time',
            'experience_required': 5
        },
        {
            'company_username': 'startup_inc',
            'title': 'Frontend Developer',
            'description': 'Join our startup as a Frontend Developer and help build the next generation of fintech applications. You\'ll work directly with our CTO and have significant impact on product direction.',
            'requirements': 'Experience with React, TypeScript, and modern CSS frameworks. 3+ years of frontend development experience. Startup experience preferred. Must be comfortable with rapid iteration and changing requirements.',
            'tags': 'React, TypeScript, Frontend, Startup, Fintech',
            'location': 'Austin, TX',
            'salary_range': '$90,000 - $130,000',
            'employment_type': 'Full-time',
            'experience_required': 3
        },
        {
            'company_username': 'design_agency',
            'title': 'UX/UI Designer',
            'description': 'Creative Design Agency is seeking a talented UX/UI Designer to join our team. You\'ll work on diverse projects for Fortune 500 clients and help shape digital experiences that millions of users interact with.',
            'requirements': 'Bachelor\'s degree in Design or related field. 3+ years of UX/UI design experience. Proficiency in Figma, Sketch, and Adobe Creative Suite. Strong portfolio demonstrating user-centered design process.',
            'tags': 'UX, UI, Figma, Design, Creative, User Experience',
            'location': 'New York, NY',
            'salary_range': '$85,000 - $115,000',
            'employment_type': 'Full-time',
            'experience_required': 3
        },
        {
            'company_username': 'techcorp',
            'title': 'DevOps Engineer',
            'description': 'Looking for a DevOps Engineer to help streamline our deployment processes and maintain our cloud infrastructure. You\'ll work with cutting-edge tools and help scale our platform to serve millions of users.',
            'requirements': 'Experience with AWS, Docker, Kubernetes, and CI/CD pipelines. Knowledge of Infrastructure as Code (Terraform/CloudFormation). 4+ years of DevOps or Site Reliability Engineering experience.',
            'tags': 'DevOps, AWS, Docker, Kubernetes, Infrastructure, CI/CD',
            'location': 'San Francisco, CA',
            'salary_range': '$130,000 - $170,000',
            'employment_type': 'Full-time',
            'experience_required': 4
        }
    ]
    
    # Insert demo jobs
    for job in demo_jobs:
        company_id = company_map.get(job['company_username'])
        if company_id:
            try:
                cursor.execute('''
                    INSERT INTO jobs 
                    (company_id, title, description, requirements, tags, location, 
                     salary_range, employment_type, experience_required)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (company_id, job['title'], job['description'], job['requirements'], 
                      job['tags'], job['location'], job['salary_range'], 
                      job['employment_type'], job['experience_required']))
            except sqlite3.IntegrityError:
                print(f"Job {job['title']} already exists, skipping...")
    
    conn.commit()
    conn.close()
    
    print("\nDemo data created successfully!")
    print("\nDemo Accounts:")
    print("Job Seekers:")
    print("  Username: john_seeker, Password: password123")
    print("  Username: jane_dev, Password: password123")
    print("  Username: mike_designer, Password: password123")
    print("\nCompanies:")
    print("  Username: techcorp, Password: password123")
    print("  Username: startup_inc, Password: password123")
    print("  Username: design_agency, Password: password123")
    print("\nYou can now log in with any of these accounts to test the application!")

if __name__ == '__main__':
    create_demo_data() 