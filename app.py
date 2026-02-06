import os

import json

import uuid

import shutil

import glob

from datetime import datetime

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, send_from_directory

from dotenv import load_dotenv



from aws_client import AwsClient

from werkzeug.security import generate_password_hash, check_password_hash



load_dotenv()



app = Flask(__name__, template_folder='templates', static_folder='static')

app.secret_key = os.environ.get('FLASK_SECRET', 'dev-secret')

# Initialize AWS client
aws = AwsClient()

# SNS Topic ARN (for development/testing)
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN', 'arn:aws:sns:us-east-1:YOUR_ACCOUNT_ID:VCC_Notifications')

# Create default admin if none exists
def ensure_default_admin():
    try:
        existing_admins = aws._read_store().get('admins', [])
        if not existing_admins:
            print("Creating default admin account...")
            aws.create_admin(
                email="admin@virtualcareercounselor.com",
                password=generate_password_hash("admin123"),
                name="System Administrator"
            )
            print("✅ Default admin created: admin@virtualcareercounselor.com / admin123")
    except Exception as e:
        print(f"Admin creation failed: {e}")

# Ensure default admin exists
ensure_default_admin()




@app.route('/')

def index():

    # If user is not logged in, redirect to login page

    if 'user_id' not in session:

        return redirect(url_for('login'))

    # If logged in, show homepage with profile, roadmap, and chat features

    is_logged_in = True

    user = aws.get_user(session.get('user_id'))

    return render_template('index.html', is_logged_in=is_logged_in, user=user)





def login_required(fn):

    from functools import wraps

    @wraps(fn)

    def wrapper(*args, **kwargs):

        if 'user_id' not in session:

            return redirect(url_for('login', next=request.path))

        return fn(*args, **kwargs)

    return wrapper





@app.route('/signup', methods=['GET', 'POST'])

def signup():

    if request.method == 'POST':

        data = request.form

        email = data.get('email')

        password = data.get('password')

        full_name = data.get('fullName')

        phone = data.get('phone')

        school = data.get('school')

        org = data.get('organization')

        address = data.get('address')

        role = data.get('role')

        if not email or not password:

            flash('Email and password required')

            return redirect(url_for('signup'))

        # Clear any existing session data before creating new user

        session.clear()

        user = aws.create_user(email=email, password=generate_password_hash(password), profile={

            'fullName': full_name, 'phone': phone, 'school': school, 'organization': org, 'address': address, 'role': role

        })

        session['user_id'] = user['userId']

        

        # Check for referral code

        referral_code = request.form.get('referralCode', '').strip()

        if referral_code:

            aws.use_referral_code(user['userId'], referral_code)

        

        # Award initial XP and badges

        aws.award_xp(user['userId'], 50, 'Account created')

        aws.award_badge(user['userId'], 'Getting Started', '🚀', 'Created your account!')

        aws.update_streak(user['userId'])

        

        return redirect(url_for('dashboard'))

    return render_template('signup.html')





@app.route('/login', methods=['GET', 'POST'])

def login():

    # If already logged in, redirect to dashboard

    if 'user_id' in session:

        return redirect(url_for('dashboard'))

    

    if request.method == 'POST':

        data = request.form

        email = data.get('email')

        password = data.get('password')

        

        if not email or not password:

            flash('Please enter both email and password', 'error')

            return render_template('login.html')

        

        user = aws.get_user_by_email(email)

        if not user:

            flash('Invalid credentials. Please check your email and password.', 'error')

            return render_template('login.html')

        

        if not check_password_hash(user.get('passwordHash', ''), password):

            flash('Invalid credentials. Please check your email and password.', 'error')

            return render_template('login.html')

        

        # Clear any existing session data and set new user session

        session.clear()

        session['user_id'] = user['userId']

        

        # Update streak and award initial badges

        aws.update_streak(user['userId'])

        aws.award_badge(user['userId'], 'Welcome!', '👋', 'Welcome to Virtual Career Counselor!')

        

        flash('Login successful!', 'success')

        return redirect(url_for('dashboard'))

    

    return render_template('login.html')





@app.route('/forgot-password', methods=['GET', 'POST'])

def forgot_password():

    if request.method == 'POST':

        email = request.form.get('email')

        if not email:

            flash('Please enter your email address', 'error')

            return render_template('forgot_password.html')

        

        user = aws.get_user_by_email(email)

        if user:

            # In a real application, you would send a password reset email here

            # For now, we'll just show a success message

            flash('If an account exists with that email, password reset instructions have been sent.', 'info')

        else:

            # Don't reveal if email exists for security

            flash('If an account exists with that email, password reset instructions have been sent.', 'info')

        

        return redirect(url_for('login'))

    

    return render_template('forgot_password.html')





@app.route('/logout')

def logout():

    # Clear session

    session.pop('user_id', None)

    session.clear()

    # Redirect to login page

    flash('You have been logged out successfully.', 'info')

    return redirect(url_for('login'))





@app.route('/images/<path:filename>')

def project_image(filename):

    # Serve images placed in the project-level images/ folder

    images_dir = os.path.join(os.path.dirname(__file__), 'images')

    return send_from_directory(images_dir, filename)





@app.route('/api/profile', methods=['POST'])

def save_profile():

    payload = request.json or {}

    # Use session user_id if logged in, otherwise create new user (for anonymous profile saving)

    user_id = session.get('user_id')

    if not user_id:

        # If not logged in, create a new user ID (for anonymous users)

        user_id = str(uuid.uuid4())

        session['user_id'] = user_id

    profile = payload.get('profile', {})

    item = {'userId': user_id, 'profile': profile, 'updatedAt': datetime.utcnow().isoformat()}

    aws.save_user_profile(item)

    # record activity and create role-based suggested activities

    aws.record_activity(user_id, 'save_profile', {'profile': profile})

    aws.create_activities_for_role(user_id, profile.get('targetRole') or profile.get('role') or profile.get('target') )

    return jsonify({'userId': user_id, 'status': 'saved'})





@app.route('/api/profile', methods=['GET'])

@login_required

def get_profile():

    user_id = session.get('user_id')

    user = aws.get_user(user_id)

    profile = {}

    if user and isinstance(user.get('profile'), dict):

        profile = user.get('profile') or {}

    return jsonify({'userId': user_id, 'profile': profile})





@app.route('/test_roadmap.html')
def test_roadmap_page():
    return render_template('test_roadmap.html')


@app.route('/api/generate-roadmap', methods=['POST'])

@login_required

def generate_roadmap():

    user_id = session.get('user_id')

    payload = request.json or {}

    goal = payload.get('goal', 'software engineer')

    context = payload.get('context', {})
    
    try:
        # Try to generate roadmap with AI
        roadmap = aws.generate_roadmap(user_id, goal, context)
        
        if roadmap and isinstance(roadmap, dict) and roadmap.get('steps'):
            # Success - record activity and award XP
            aws.record_activity(user_id, 'generate_roadmap', {'roadmapId': roadmap.get('roadmapId')})
            try:
                aws.award_xp(user_id, 25, 'Generated a roadmap')
            except Exception:
                pass  # XP awarding is optional
            return jsonify({'roadmap': roadmap, 'success': True})
        else:
            # AI failed but didn't throw exception, use fallback
            raise Exception("AI generation returned empty roadmap")
            
    except Exception as e:
        # Final fallback - create a basic roadmap
        print(f"Roadmap generation failed, using fallback: {str(e)}")
        
        # Create a detailed profession-specific roadmap
        def get_roadmap_for_profession(profession):
            profession = profession.lower()
            
            if 'teacher' in profession or 'teaching' in profession:
                return [
                    {
                        'title': 'Educational Foundation & Certification',
                        'description': 'Complete a bachelor\'s degree in education or your subject area. Research and obtain required teaching certification/license for your region. Pass required certification exams (e.g., Praxis, state-specific tests).'
                    },
                    {
                        'title': 'Subject Knowledge & Curriculum Mastery',
                        'description': 'Deepen expertise in your subject area through advanced coursework. Study current curriculum standards and educational technology tools. Stay updated with pedagogical research.'
                    },
                    {
                        'title': 'Lesson Planning & Instructional Design',
                        'description': 'Learn to create scaffolded lesson plans with clear objectives. Practice designing differentiated instruction for diverse learners. Build a collection of teaching materials.'
                    },
                    {
                        'title': 'Classroom Management & Student Engagement',
                        'description': 'Study effective classroom management strategies. Learn active learning methods and student engagement techniques. Gain experience through student teaching or volunteer work.'
                    },
                    {
                        'title': 'Assessment & Professional Growth',
                        'description': 'Master formative and summative assessment techniques. Learn to provide constructive feedback. Join professional teaching organizations and attend workshops.'
                    },
                    {
                        'title': 'Job Search & Career Launch',
                        'description': 'Create a comprehensive teaching portfolio. Prepare all required certification documents. Network with educators and attend job fairs. Apply to school districts.'
                    }
                ]
            
            elif 'software' in profession or 'engineer' in profession or 'developer' in profession:
                return [
                    {
                        'title': 'Programming Foundations & Core Concepts',
                        'description': 'Master one programming language deeply (Python, JavaScript, or Java). Learn fundamental data structures and algorithms. Understand time/space complexity and problem-solving techniques.'
                    },
                    {
                        'title': 'Development Tools & Version Control',
                        'description': 'Become proficient with Git and GitHub. Learn to use IDEs effectively. Understand command-line tools and package managers. Set up development environments.'
                    },
                    {
                        'title': 'Web Development & Full-Stack Projects',
                        'description': 'Learn frontend (HTML, CSS, JavaScript, React) and backend (Node.js, Python/Django). Understand databases and API design. Build 3-5 substantial projects.'
                    },
                    {
                        'title': 'Software Engineering Practices',
                        'description': 'Learn software testing (unit, integration tests). Understand CI/CD pipelines. Study design patterns and software architecture. Practice code reviews and clean code.'
                    },
                    {
                        'title': 'System Design & Interview Preparation',
                        'description': 'Study system design concepts (scalability, load balancing). Practice coding interview problems on LeetCode. Learn common interview patterns and behavioral questions.'
                    },
                    {
                        'title': 'Portfolio & Job Search',
                        'description': 'Create a professional GitHub profile. Build a portfolio website. Optimize LinkedIn profile and resume. Network with developers and apply to positions.'
                    }
                ]
            
            elif 'data' in profession or 'analyst' in profession:
                return [
                    {
                        'title': 'Foundational Skills: SQL & Statistics',
                        'description': 'Master SQL for querying databases. Learn statistical concepts (descriptive statistics, probability, hypothesis testing). Practice with real datasets on Kaggle.'
                    },
                    {
                        'title': 'Programming & Data Tools',
                        'description': 'Learn Python for data analysis (pandas, NumPy). Master Excel for basic analytics. Learn data visualization libraries (Matplotlib, Seaborn, Tableau).'
                    },
                    {
                        'title': 'Data Visualization & Business Intelligence',
                        'description': 'Learn visualization tools like Tableau or Power BI. Master creating dashboards that tell compelling data stories. Practice with real business datasets.'
                    },
                    {
                        'title': 'Data Analysis Projects',
                        'description': 'Complete end-to-end data analysis projects. Work on projects across different domains. Document your analysis process and findings. Build a portfolio of 3-5 projects.'
                    },
                    {
                        'title': 'Advanced Analytics & Machine Learning',
                        'description': 'Learn machine learning fundamentals. Practice building predictive models with scikit-learn. Understand when to use different ML algorithms. Focus on practical applications.'
                    },
                    {
                        'title': 'Portfolio & Career Launch',
                        'description': 'Create a GitHub portfolio with Jupyter notebooks. Write case studies explaining your methodology. Prepare for data analyst interviews. Network with data professionals.'
                    }
                ]
            
            elif 'ux' in profession or 'designer' in profession:
                return [
                    {
                        'title': 'UX Design Foundations & Design Thinking',
                        'description': 'Learn fundamental UX principles and design thinking methodology. Study user research methods (interviews, surveys, personas). Understand information architecture.'
                    },
                    {
                        'title': 'Design Tools & Prototyping Skills',
                        'description': 'Master design tools like Figma, Sketch, or Adobe XD. Learn to create wireframes, mockups, and interactive prototypes. Understand design systems.'
                    },
                    {
                        'title': 'User Research & Usability Testing',
                        'description': 'Learn to conduct user interviews and usability tests. Analyze research findings and synthesize insights. Create user personas and journey maps.'
                    },
                    {
                        'title': 'Portfolio Development: Case Studies',
                        'description': 'Complete 3-5 comprehensive UX design projects. Document your process from research to final design. Create detailed case studies showing your thinking.'
                    },
                    {
                        'title': 'Accessibility & Metrics',
                        'description': 'Learn accessibility standards (WCAG guidelines). Understand how to measure UX success. Learn A/B testing and data-driven design decisions.'
                    },
                    {
                        'title': 'Interview Preparation & Career Launch',
                        'description': 'Prepare portfolio website showcasing best case studies. Practice portfolio walkthroughs. Network with UX designers. Apply to UX positions.'
                    }
                ]
            
            else:
                # Generic fallback for any profession
                return [
                    {
                        'title': f'Research & Education Foundation for {goal}',
                        'description': f'Research the {goal} profession thoroughly. Identify required qualifications, certifications, and educational background. Enroll in relevant courses or degree programs.'
                    },
                    {
                        'title': 'Skill Development & Practical Experience',
                        'description': f'Develop both technical and soft skills relevant to {goal}. Gain hands-on experience through projects, internships, or volunteer work. Practice using industry-standard tools.'
                    },
                    {
                        'title': 'Professional Tools & Industry Knowledge',
                        'description': f'Master tools, software, and technologies commonly used in {goal} roles. Understand industry workflows and methodologies. Stay updated with industry trends.'
                    },
                    {
                        'title': 'Networking & Professional Development',
                        'description': f'Build a professional network by connecting with {goal} professionals. Attend industry events, conferences, or meetups. Seek mentorship from experienced professionals.'
                    },
                    {
                        'title': 'Portfolio & Interview Preparation',
                        'description': f'Create a comprehensive portfolio showcasing your skills and achievements relevant to {goal}. Prepare for role-specific interviews and practice common questions.'
                    },
                    {
                        'title': 'Job Search & Career Launch',
                        'description': f'Optimize your resume and LinkedIn profile for {goal} positions. Apply strategically to entry-level positions. Follow up on applications and maintain persistence.'
                    }
                ]
        
        basic_steps = get_roadmap_for_profession(goal)
        
        fallback_roadmap = {
            'roadmapId': str(uuid.uuid4()),
            'userId': user_id,
            'goal': goal,
            'steps': basic_steps,
            'generatedAt': datetime.utcnow().isoformat(),
            'isFallback': True
        }
        
        # Save the fallback roadmap
        try:
            aws.save_roadmap(fallback_roadmap)
            aws.record_activity(user_id, 'generate_roadmap', {'roadmapId': fallback_roadmap.get('roadmapId')})
            aws.award_xp(user_id, 25, 'Generated a roadmap')
        except Exception:
            pass  # Even saving failed, but we still return the roadmap
        
        return jsonify({'roadmap': fallback_roadmap, 'success': True, 'fallback': True})


def verify_roadmap_ownership(roadmap_id, user_id):
    """Verify that roadmap belongs to the logged-in user"""
    roadmaps = aws.list_roadmaps_for_user(user_id)

    for r in roadmaps:

        if r.get('roadmapId') == roadmap_id:

            return r

    return None





@app.route('/api/roadmap/<roadmap_id>', methods=['GET'])

@login_required

def get_roadmap(roadmap_id):

    user_id = session.get('user_id')

    # Verify roadmap belongs to current user

    roadmap = verify_roadmap_ownership(roadmap_id, user_id)

    if not roadmap:

        return jsonify({'error': 'access denied'}), 403

    return jsonify({'roadmap': roadmap})





@app.route('/roadmap/<roadmap_id>')

@login_required

def view_roadmap(roadmap_id):

    user_id = session.get('user_id')

    # Verify roadmap belongs to current user

    roadmap = verify_roadmap_ownership(roadmap_id, user_id)

    if not roadmap:

        return "Access denied or roadmap not found", 403

    return render_template('roadmap_view.html', roadmap=roadmap)





@app.route('/dashboard')

@login_required

def dashboard():

    user_id = session.get('user_id')

    user = aws.get_user(user_id)

    roadmaps = aws.list_roadmaps_for_user(user_id)

    activities = aws.list_user_activities(user_id)

    gamification = aws.get_gamification_stats(user_id)

    notifications = aws.get_notifications(user_id, unread_only=True)

    return render_template('dashboard.html', user=user, roadmaps=roadmaps, activities=activities, gamification=gamification, unreadNotifications=len(notifications))



@app.route('/profile')

@login_required

def profile_page():

    return render_template('profile.html')





@app.route('/settings')

@login_required

def settings_page():

    return render_template('settings.html')





@app.route('/api/dashboard-data')

@login_required

def dashboard_data():

    user_id = session.get('user_id')

    user = aws.get_user(user_id)

    roadmaps = aws.list_roadmaps_for_user(user_id)

    activities = aws.list_user_activities(user_id)

    return jsonify({'user': user, 'roadmaps': roadmaps, 'activities': activities})





@app.route('/activities')

@login_required

def activities_page():

    user_id = session.get('user_id')

    activities = aws.list_user_activities(user_id)

    return render_template('activities.html', activities=activities)





@app.route('/api/activities')

@login_required

def api_list_activities():

    user_id = session.get('user_id')

    user = aws.get_user(user_id)

    all_activities = aws.list_user_activities(user_id)

    

    # Filter to only show activities matching user's current target profession

    current_profession = None

    if user and user.get('profile'):

        current_profession = (user['profile'].get('targetRole') or user['profile'].get('role') or '').lower()

    

    # If user has a target profession set, filter activities to only that profession

    if current_profession:

        filtered = [a for a in all_activities if (a.get('role') or '').lower() == current_profession]

        return jsonify({'activities': filtered})

    

    return jsonify({'activities': all_activities})





@app.route('/api/activities/complete', methods=['POST'])

@login_required

def api_complete_activity():

    user_id = session.get('user_id')

    payload = request.json or {}

    activity_id = payload.get('activityId')

    if not activity_id:

        return jsonify({'error': 'missing activityId'}), 400

    ok = aws.complete_activity(user_id, activity_id)

    if ok:

        aws.record_activity(user_id, 'complete_activity', {'activityId': activity_id})

        return jsonify({'status': 'completed'})

    return jsonify({'error': 'not found'}), 404





def verify_activity_ownership(activity_id, user_id):

    """Verify that activity belongs to the logged-in user"""

    activities = aws.list_user_activities(user_id)

    for a in activities:

        if a.get('activityId') == activity_id:

            return a

    return None





@app.route('/quiz/<activity_id>')

@login_required

def quiz_page(activity_id):

    user_id = session.get('user_id')

    # Verify activity belongs to current user

    activity = verify_activity_ownership(activity_id, user_id)

    if not activity:

        return "Access denied or quiz not found", 403

    qa = aws.get_quiz_for_activity(activity_id)

    if not qa:

        return "Quiz not found", 404

    return render_template('quiz.html', activity=qa['activity'], quiz=qa['quiz'])





@app.route('/api/quiz/<activity_id>')

@login_required

def api_get_quiz(activity_id):

    user_id = session.get('user_id')

    # Verify activity belongs to current user

    activity = verify_activity_ownership(activity_id, user_id)

    if not activity:

        return jsonify({'error': 'access denied'}), 403

    qa = aws.get_quiz_for_activity(activity_id)

    if not qa:

        return jsonify({'error': 'not found'}), 404

    return jsonify({'activity': qa['activity'], 'quiz': qa['quiz']})





@app.route('/api/quiz/submit', methods=['POST'])

@login_required

def api_submit_quiz():

    user_id = session.get('user_id')

    payload = request.json or {}

    activity_id = payload.get('activityId')

    answers = payload.get('answers', {})

    if not activity_id:

        return jsonify({'error': 'missing activityId'}), 400

    # Verify activity belongs to current user

    activity = verify_activity_ownership(activity_id, user_id)

    if not activity:

        return jsonify({'error': 'access denied'}), 403

    result = aws.grade_quiz(activity_id, answers)

    if result is None:

        return jsonify({'error': 'not found'}), 404

    

    score = result.get('score', 0)

    # record activity event

    aws.record_activity(user_id, 'quiz_completed', {'activityId': activity_id, 'score': score})

    

    # Award XP based on score

    xp_amount = max(10, int(score / 10))  # 10-100 XP based on score

    aws.award_xp(user_id, xp_amount, f'Quiz completed: {score}%')

    

    # Award badges for perfect scores

    if score == 100:

        aws.award_badge(user_id, 'Perfect Score', '💯', 'Scored 100% on a quiz!')

    elif score >= 90:

        aws.award_badge(user_id, 'Excellent', '⭐', 'Scored 90% or above!')

    

    return jsonify({'result': result})





@app.route('/leaderboard')

@login_required

def leaderboard_page():

    return render_template('leaderboard.html')





@app.route('/api/leaderboard')

@login_required

def api_leaderboard():

    top = int(request.args.get('top', 10))

    rows = aws.get_leaderboard(top)

    return jsonify({'rows': rows})





@app.route('/api/chat', methods=['POST'])

def chat():

    payload = request.json or {}

    # Use session user_id if logged in, otherwise use payload (for anonymous chat)

    user_id = session.get('user_id') or payload.get('userId')

    if not user_id:

        # Create anonymous user ID if neither session nor payload has it

        user_id = str(uuid.uuid4())

        session['user_id'] = user_id

    message = payload.get('message', '')

    

    # Use enhanced chat if user is logged in, otherwise use basic chat

    if session.get('user_id'):

        response = aws.enhanced_chat(user_id, message)

    else:

        response = aws.chat_with_provider(user_id, message)

        aws.record_activity(user_id, 'chat', {'message': message, 'reply': response})

    

    return jsonify({'reply': response})





# Career Path Exploration

@app.route('/career-explore')

@login_required

def career_explore_page():

    return render_template('career_explore.html')





@app.route('/api/career-explore', methods=['POST'])

@login_required

def api_career_explore():

    payload = request.json or {}

    career_name = payload.get('career', '').strip()

    if not career_name:

        return jsonify({'error': 'Career name is required'}), 400

    user_id = session.get('user_id')

    result = aws.explore_career_path(career_name, user_id)

    return jsonify({'career_data': result})





# Course Recommendations

@app.route('/courses')

@login_required

def courses_page():

    return render_template('courses.html')





@app.route('/api/course-recommendations', methods=['POST'])

@login_required

def api_course_recommendations():

    user_id = session.get('user_id')

    payload = request.json or {}

    preferences = payload.get('preferences', {})

    career_name = payload.get('career', None)  # Get career from request

    result = aws.get_course_recommendations(user_id, preferences, career_name)

    return jsonify({'recommendations': result})





# Job Market Insights

@app.route('/job-insights')

@login_required

def job_insights_page():

    return render_template('job_insights.html')





@app.route('/api/job-insights', methods=['POST'])

@login_required

def api_job_insights():

    payload = request.json or {}

    career_name = payload.get('career', '').strip()

    region = payload.get('region', '').strip()

    if not career_name:

        return jsonify({'error': 'Career name is required'}), 400

    result = aws.get_job_market_insights(career_name, region)

    return jsonify({'insights': result})





# Admin Authentication

@app.route('/admin/login', methods=['GET', 'POST'])

def admin_login():

    if request.method == 'POST':

        data = request.form

        email = data.get('email')

        password = data.get('password')

        

        if not email or not password:

            flash('Please enter both email and password', 'error')

            return render_template('admin_login.html')

        

        admin = aws.get_admin_by_email(email)

        if not admin:

            flash('Invalid credentials', 'error')

            return render_template('admin_login.html')

        

        if not check_password_hash(admin.get('passwordHash', ''), password):

            flash('Invalid credentials', 'error')

            return render_template('admin_login.html')

        

        session.clear()

        session['admin_id'] = admin['adminId']

        session['is_admin'] = True

        flash('Login successful!', 'success')

        return redirect(url_for('admin_dashboard'))

    

    # If already logged in as admin, redirect to dashboard

    if 'admin_id' in session and session.get('is_admin'):

        return redirect(url_for('admin_dashboard'))

    

    return render_template('admin_login.html')





@app.route('/admin/logout')

def admin_logout():

    session.pop('admin_id', None)

    session.pop('is_admin', None)

    session.clear()

    flash('You have been logged out successfully.', 'info')

    return redirect(url_for('admin_login'))





def admin_required(fn):

    from functools import wraps

    @wraps(fn)

    def wrapper(*args, **kwargs):

        if 'admin_id' not in session or not session.get('is_admin'):

            return redirect(url_for('admin_login'))

        return fn(*args, **kwargs)

    return wrapper





# Admin Dashboard

@app.route('/admin/dashboard')

@admin_required

def admin_dashboard():

    admin_id = session.get('admin_id')

    admin = aws.get_admin(admin_id)

    jobs = aws.list_jobs(status='active')

    applications = aws.list_applications_for_admin(admin_id)

    return render_template('admin_dashboard.html', admin=admin, jobs=jobs, applications=applications)





# Admin Job Management

@app.route('/admin/jobs', methods=['GET', 'POST'])

@admin_required

def admin_jobs():

    admin_id = session.get('admin_id')

    if request.method == 'POST':

        data = request.json or request.form

        job_data = {

            'title': data.get('title', ''),

            'company': data.get('company', ''),

            'description': data.get('description', ''),

            'requirements': data.get('requirements', []),

            'experience_required': data.get('experience_required', ''),

            'salary_range': data.get('salary_range', ''),

            'location': data.get('location', ''),

            'job_type': data.get('job_type', 'Full-time'),

            'career_field': data.get('career_field', '')

        }

        job = aws.create_job_posting(admin_id, job_data)

        if request.is_json:

            return jsonify({'job': job, 'status': 'created'})

        flash('Job posted successfully!', 'success')

        return redirect(url_for('admin_jobs'))

    

    jobs = aws.list_jobs()

    return render_template('admin_jobs.html', jobs=jobs)





@app.route('/admin/jobs/<job_id>/delete', methods=['POST'])

@admin_required

def admin_delete_job(job_id):

    admin_id = session.get('admin_id')

    job = aws.get_job(job_id)

    if job and job.get('adminId') == admin_id:

        aws.delete_job(job_id)

        flash('Job deleted successfully!', 'success')

    else:

        flash('Job not found or unauthorized', 'error')

    return redirect(url_for('admin_jobs'))





# Admin Application Management

@app.route('/admin/applications')

@admin_required

def admin_applications():

    admin_id = session.get('admin_id')

    applications = aws.list_applications_for_admin(admin_id)

    # Get job details for each application

    for app in applications:

        job = aws.get_job(app.get('jobId'))

        app['job'] = job

    return render_template('admin_applications.html', applications=applications)





@app.route('/admin/applications/<application_id>/update', methods=['POST'])

@admin_required

def admin_update_application(application_id):

    data = request.json or request.form

    status = data.get('status', 'pending')

    admin_notes = data.get('admin_notes', '')

    

    if aws.update_application_status(application_id, status, admin_notes):

        if request.is_json:

            return jsonify({'status': 'updated'})

        flash('Application status updated!', 'success')

    else:

        if request.is_json:

            return jsonify({'error': 'Application not found'}), 404

        flash('Application not found', 'error')

    

    return redirect(url_for('admin_applications'))





# Public Job Listings (for users)

@app.route('/api/jobs', methods=['GET'])

@login_required

def api_list_jobs():

    career_field = request.args.get('career', '').strip()

    jobs = aws.list_jobs(career_field=career_field if career_field else None)

    return jsonify({'jobs': jobs})





# Job Application

@app.route('/api/jobs/<job_id>/apply', methods=['POST'])

@login_required

def api_apply_job(job_id):

    user_id = session.get('user_id')

    payload = request.json or {}

    

    job = aws.get_job(job_id)

    if not job or job.get('status') != 'active':

        return jsonify({'error': 'Job not found or not available'}), 404

    

    application_data = {

        'fullName': payload.get('fullName', ''),

        'email': payload.get('email', ''),

        'phone': payload.get('phone', ''),

        'experience': payload.get('experience', ''),

        'skills': payload.get('skills', []),

        'education': payload.get('education', ''),

        'coverLetter': payload.get('coverLetter', '')

    }

    

    application = aws.create_job_application(user_id, job_id, application_data)

    

    # Award XP and send notification

    aws.award_xp(user_id, 15, 'Applied for a job')

    aws.create_notification(

        user_id, 'application_update',

        'Application Submitted! 📝',

        f'Your application has been submitted successfully.',

        f'/api/my-applications'

    )

    

    return jsonify({'application': application, 'status': 'submitted'})





@app.route('/api/my-applications')

@login_required

def api_my_applications():

    user_id = session.get('user_id')

    applications = aws.list_user_applications(user_id)

    # Get job details for each application

    for app in applications:

        job = aws.get_job(app.get('jobId'))

        app['job'] = job

    return jsonify({'applications': applications})





# ========== NEW FEATURES ROUTES ==========



# Portfolio Management

@app.route('/api/portfolio', methods=['GET', 'POST'])

@login_required

def api_portfolio():

    user_id = session.get('user_id')

    if request.method == 'POST':

        portfolio_data = request.json or {}

        portfolio = aws.update_portfolio(user_id, portfolio_data)

        return jsonify({'portfolio': portfolio, 'status': 'saved'})

    else:

        portfolio = aws.get_portfolio(user_id)

        return jsonify({'portfolio': portfolio})



@app.route('/profile/<public_id>')

def public_profile(public_id):

    """Public shareable profile page"""

    user = aws.get_user_by_public_id(public_id)

    if not user:

        return "Profile not found", 404

    public_data = aws.get_public_profile(user['userId'])

    return render_template('public_profile.html', profile=public_data)



@app.route('/api/generate-public-link')

@login_required

def api_generate_public_link():

    user_id = session.get('user_id')

    public_id = aws.generate_public_profile_id(user_id)

    return jsonify({'publicId': public_id, 'url': f'/profile/{public_id}'})



# Saved Jobs & Favorites

@app.route('/api/jobs/<job_id>/save', methods=['POST'])

@login_required

def api_save_job(job_id):

    user_id = session.get('user_id')

    if aws.save_job(user_id, job_id):

        aws.award_xp(user_id, 5, 'Saved a job')

        return jsonify({'status': 'saved'})

    return jsonify({'status': 'already_saved'}), 200



@app.route('/api/jobs/<job_id>/unsave', methods=['POST'])

@login_required

def api_unsave_job(job_id):

    user_id = session.get('user_id')

    if aws.unsave_job(user_id, job_id):

        return jsonify({'status': 'unsaved'})

    return jsonify({'error': 'not found'}), 404



@app.route('/api/saved-jobs')

@login_required

def api_saved_jobs():

    user_id = session.get('user_id')

    saved_job_ids = aws.get_saved_jobs(user_id)

    jobs = []

    for job_id in saved_job_ids:

        job = aws.get_job(job_id)

        if job:

            jobs.append(job)

    return jsonify({'jobs': jobs})



@app.route('/api/roadmaps/<roadmap_id>/save', methods=['POST'])

@login_required

def api_save_roadmap(roadmap_id):

    user_id = session.get('user_id')

    if aws.save_roadmap(user_id, roadmap_id):

        aws.award_xp(user_id, 5, 'Saved a roadmap')

        return jsonify({'status': 'saved'})

    return jsonify({'status': 'already_saved'}), 200



# Notifications

@app.route('/api/notifications')

@login_required

def api_notifications():

    user_id = session.get('user_id')

    unread_only = request.args.get('unread_only', 'false').lower() == 'true'

    notifications = aws.get_notifications(user_id, unread_only=unread_only)

    unread_count = len([n for n in notifications if not n.get('read', False)])

    return jsonify({'notifications': notifications, 'unreadCount': unread_count})



@app.route('/api/notifications/<notification_id>/read', methods=['POST'])

@login_required

def api_mark_notification_read(notification_id):

    user_id = session.get('user_id')

    if aws.mark_notification_read(notification_id, user_id):

        return jsonify({'status': 'read'})

    return jsonify({'error': 'not found'}), 404



@app.route('/api/notifications/read-all', methods=['POST'])

@login_required

def api_mark_all_notifications_read():

    user_id = session.get('user_id')

    aws.mark_all_notifications_read(user_id)

    return jsonify({'status': 'all_read'})



# Gamification

@app.route('/api/gamification')

@login_required

def api_gamification():

    user_id = session.get('user_id')

    stats = aws.get_gamification_stats(user_id)

    return jsonify({'stats': stats})



@app.route('/api/gamification/update-streak', methods=['POST'])

@login_required

def api_update_streak():

    user_id = session.get('user_id')

    stats = aws.update_streak(user_id)

    return jsonify({'stats': stats})



# Resume Builder

@app.route('/resume-builder')

@login_required

def resume_builder_page():

    return render_template('resume_builder.html')



@app.route('/api/resumes', methods=['GET', 'POST'])

@login_required

def api_resumes():

    user_id = session.get('user_id')

    if request.method == 'POST':

        resume_data = request.json or {}

        resume = aws.save_resume(user_id, resume_data)

        aws.award_xp(user_id, 20, 'Created a resume')

        return jsonify({'resume': resume, 'status': 'created'})

    else:

        resumes = aws.get_resumes(user_id)

        return jsonify({'resumes': resumes})



@app.route('/api/resumes/<resume_id>', methods=['GET', 'DELETE'])

@login_required

def api_resume(resume_id):

    user_id = session.get('user_id')

    if request.method == 'DELETE':

        if aws.delete_resume(user_id, resume_id):

            return jsonify({'status': 'deleted'})

        return jsonify({'error': 'not found'}), 404

    else:

        resume = aws.get_resume(user_id, resume_id)

        if resume:

            return jsonify({'resume': resume})

        return jsonify({'error': 'not found'}), 404



@app.route('/api/resumes/<resume_id>/export', methods=['POST'])

@login_required

def api_export_resume(resume_id):

    user_id = session.get('user_id')

    resume = aws.get_resume(user_id, resume_id)

    if not resume:

        return jsonify({'error': 'not found'}), 404

    

    format_type = request.json.get('format', 'pdf') if request.is_json else 'pdf'

    # Return resume data for client-side PDF generation

    return jsonify({'resume': resume, 'format': format_type})



# Export & Sharing

@app.route('/api/roadmaps/<roadmap_id>/share', methods=['POST'])

@login_required

def api_share_roadmap(roadmap_id):

    user_id = session.get('user_id')

    roadmap = aws.get_roadmap(roadmap_id)

    if not roadmap or roadmap.get('userId') != user_id:

        return jsonify({'error': 'not found'}), 404

    

    # Generate shareable link

    share_url = f"{request.host_url}roadmap/{roadmap_id}"

    return jsonify({'url': share_url, 'roadmap': roadmap})



@app.route('/api/export/progress-report', methods=['POST'])

@login_required

def api_export_progress_report():

    user_id = session.get('user_id')

    user = aws.get_user(user_id)

    roadmaps = aws.list_roadmaps_for_user(user_id)

    activities = aws.list_user_activities(user_id)

    gamification = aws.get_gamification_stats(user_id)

    applications = aws.list_user_applications(user_id)

    

    completed_activities = [a for a in activities if a.get('status') == 'completed']

    

    report = {

        'user': user.get('profile', {}).get('fullName', 'User'),

        'generatedAt': datetime.utcnow().isoformat(),

        'summary': {

            'roadmaps': len(roadmaps),

            'activitiesCompleted': len(completed_activities),

            'totalActivities': len(activities),

            'applications': len(applications),

            'level': gamification.get('level', 1),

            'xp': gamification.get('xp', 0),

            'badges': len(gamification.get('badges', [])),

            'streak': gamification.get('streak', 0)

        },

        'roadmaps': [{'goal': r.get('goal'), 'createdAt': r.get('generatedAt')} for r in roadmaps],

        'completedActivities': [{'title': a.get('title'), 'score': a.get('lastScore')} for a in completed_activities[:10]],

        'badges': gamification.get('badges', [])

    }

    

    return jsonify({'report': report})



# Interview Preparation

@app.route('/interview-prep')

@login_required

def interview_prep_page():

    return render_template('interview_prep.html')



@app.route('/api/interview-prep/questions', methods=['POST'])

@login_required

def api_interview_questions():

    user_id = session.get('user_id')

    payload = request.json or {}

    role = payload.get('role', '')

    if not role:

        user = aws.get_user(user_id)

        role = (user.get('profile', {}).get('targetRole') or 'general').lower()

    

    # Use Groq to generate interview questions

    if aws.groq_client:

        try:

            prompt = f"""Generate 10 common interview questions for a {role} position. Format as JSON:

{{

  "role": "{role}",

  "questions": [

    {{

      "question": "Question text",

      "category": "Technical/Behavioral/Situational",

      "tips": "Answering tips",

      "sample_answer": "Sample answer structure"

    }}

  ]

}}"""

            chat_completion = aws.groq_client.chat.completions.create(

                messages=[

                    {'role': 'system', 'content': 'You are an interview preparation expert.'},

                    {'role': 'user', 'content': prompt}

                ],

                model=os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant'),

                temperature=0.7,

                max_tokens=2000,

                response_format={"type": "json_object"}

            )

            result = json.loads(chat_completion.choices[0].message.content)

            return jsonify({'questions': result.get('questions', [])})

        except Exception as e:

            pass

    

    # Fallback

    return jsonify({'questions': [

        {'question': f'Tell me about yourself', 'category': 'Behavioral', 'tips': 'Focus on relevant experience', 'sample_answer': 'Structure: Current role, relevant experience, why interested'},

        {'question': f'Why do you want to work as a {role}?', 'category': 'Behavioral', 'tips': 'Show passion and alignment', 'sample_answer': 'Mention interest, skills match, growth opportunities'}

    ]})



# Analytics Dashboard

@app.route('/analytics')

@login_required

def analytics_page():

    return render_template('analytics.html')



@app.route('/saved-jobs')

@login_required

def saved_jobs_page():

    return render_template('saved_jobs.html')



@app.route('/api/analytics')

@login_required

def api_analytics():

    user_id = session.get('user_id')

    user = aws.get_user(user_id)

    roadmaps = aws.list_roadmaps_for_user(user_id)

    activities = aws.list_user_activities(user_id)

    applications = aws.list_user_applications(user_id)

    gamification = aws.get_gamification_stats(user_id)

    

    completed_activities = [a for a in activities if a.get('status') == 'completed']

    avg_score = sum(a.get('lastScore', 0) for a in completed_activities) / len(completed_activities) if completed_activities else 0

    

    return jsonify({

        'roadmapsCount': len(roadmaps),

        'activitiesCount': len(activities),

        'completedCount': len(completed_activities),

        'applicationsCount': len(applications),

        'averageScore': round(avg_score, 1),

        'gamification': gamification,

        'progress': {

            'activities': round((len(completed_activities) / max(1, len(activities))) * 100, 1),

            'roadmaps': len(roadmaps)

        }

    })



# ========== ADDITIONAL ENHANCED FEATURES ==========



# Social Networking

@app.route('/connections')

@login_required

def connections_page():

    return render_template('connections.html')



@app.route('/api/connections/request', methods=['POST'])

@login_required

def api_send_connection_request():

    user_id = session.get('user_id')

    payload = request.json or {}

    to_user_id = payload.get('toUserId')

    message = payload.get('message')

    

    if not to_user_id:

        return jsonify({'error': 'toUserId required'}), 400

    

    connection = aws.send_connection_request(user_id, to_user_id, message)

    if connection:

        aws.award_xp(user_id, 10, 'Sent connection request')

        return jsonify({'connection': connection, 'status': 'sent'})

    return jsonify({'error': 'Request already exists'}), 400



@app.route('/api/connections/accept/<connection_id>', methods=['POST'])

@login_required

def api_accept_connection(connection_id):

    user_id = session.get('user_id')

    if aws.accept_connection(connection_id, user_id):

        aws.award_xp(user_id, 20, 'Accepted connection')

        return jsonify({'status': 'accepted'})

    return jsonify({'error': 'not found'}), 404



@app.route('/api/connections')

@login_required

def api_get_connections():

    user_id = session.get('user_id')

    connections = aws.get_connections(user_id)

    return jsonify({'connections': connections})



@app.route('/mentors')

@login_required

def mentors_page():

    return render_template('mentors.html')



@app.route('/api/mentors')

@login_required

def api_find_mentors():

    user_id = session.get('user_id')

    career_field = request.args.get('career', '').strip()

    mentors = aws.find_mentors(user_id, career_field)

    return jsonify({'mentors': mentors})



@app.route('/forum')

@login_required

def forum_page():

    return render_template('forum.html')



@app.route('/api/forum/posts', methods=['GET', 'POST'])

@login_required

def api_forum_posts():

    user_id = session.get('user_id')

    if request.method == 'POST':

        payload = request.json or {}

        post = aws.create_forum_post(

            user_id,

            payload.get('careerField', ''),

            payload.get('title', ''),

            payload.get('content', '')

        )

        aws.award_xp(user_id, 15, 'Created forum post')

        return jsonify({'post': post, 'status': 'created'})

    else:

        career_field = request.args.get('career', '').strip() or None

        posts = aws.get_forum_posts(career_field)

        return jsonify({'posts': posts})



# AI Career Matching

@app.route('/career-match')

@login_required

def career_match_page():

    return render_template('career_match.html')



@app.route('/api/career-match', methods=['POST'])

@login_required

def api_career_match():

    user_id = session.get('user_id')

    payload = request.json or {}

    answers = payload.get('answers', {})

    result = aws.career_personality_test(user_id, answers)

    aws.award_xp(user_id, 30, 'Completed personality test')

    return jsonify({'results': result})



# Salary Negotiation

@app.route('/salary-negotiation')

@login_required

def salary_negotiation_page():

    return render_template('salary_negotiation.html')



@app.route('/api/salary-negotiation', methods=['POST'])

@login_required

def api_salary_negotiation():

    payload = request.json or {}

    role = payload.get('role', '')

    current_salary = payload.get('currentSalary')

    offer_amount = payload.get('offerAmount')

    location = payload.get('location')

    

    if not role:

        return jsonify({'error': 'Role required'}), 400

    

    tips = aws.get_salary_negotiation_tips(role, current_salary, offer_amount, location)

    return jsonify({'tips': tips})



# Company Insights

@app.route('/company-insights')

@login_required

def company_insights_page():

    return render_template('company_insights.html')



@app.route('/api/company-insights/<company_name>')

@login_required

def api_get_company_insights(company_name):

    insights = aws.get_company_insights(company_name)

    return jsonify({'insights': insights})



@app.route('/api/company-reviews', methods=['GET', 'POST'])

@login_required

def api_company_reviews():

    user_id = session.get('user_id')

    if request.method == 'POST':

        payload = request.json or {}

        company_name = payload.get('companyName', '')

        review_data = payload.get('review', {})

        

        if not company_name:

            return jsonify({'error': 'Company name required'}), 400

        

        review = aws.add_company_review(user_id, company_name, review_data)

        aws.award_xp(user_id, 25, 'Added company review')

        return jsonify({'review': review, 'status': 'created'})

    else:

        company_name = request.args.get('company', '').strip()

        if not company_name:

            return jsonify({'error': 'Company name required'}), 400

        reviews = aws.get_company_reviews(company_name)

        return jsonify({'reviews': reviews})



# Enhanced Chat

@app.route('/api/chat-enhanced', methods=['POST'])

@login_required

def api_enhanced_chat():

    user_id = session.get('user_id')

    payload = request.json or {}

    message = payload.get('message', '')

    context = payload.get('context')

    

    if not message:

        return jsonify({'error': 'Message required'}), 400

    

    response = aws.enhanced_chat(user_id, message, context)

    return jsonify({'reply': response})



# Learning Paths

@app.route('/learning-paths')

@login_required

def learning_paths_page():

    return render_template('learning_paths.html')



@app.route('/api/learning-paths', methods=['GET', 'POST'])

@login_required

def api_learning_paths():

    user_id = session.get('user_id')

    if request.method == 'POST':

        payload = request.json or {}

        career_field = payload.get('careerField', '')

        milestones = payload.get('milestones', [])

        

        if not career_field or not milestones:

            return jsonify({'error': 'careerField and milestones required'}), 400

        

        path = aws.create_learning_path(user_id, career_field, milestones)

        aws.award_xp(user_id, 20, 'Created learning path')

        return jsonify({'path': path, 'status': 'created'})

    else:

        paths = aws.get_learning_paths(user_id)

        return jsonify({'paths': paths})



@app.route('/api/learning-paths/<path_id>/complete-milestone', methods=['POST'])

@login_required

def api_complete_milestone(path_id):

    user_id = session.get('user_id')

    payload = request.json or {}

    milestone_index = payload.get('milestoneIndex', 0)

    

    if aws.complete_milestone(user_id, path_id, milestone_index):

        return jsonify({'status': 'completed'})

    return jsonify({'error': 'not found'}), 404



# Referral Program

@app.route('/referrals')

@login_required

def referrals_page():

    return render_template('referrals.html')



@app.route('/api/referrals/code')

@login_required

def api_get_referral_code():

    user_id = session.get('user_id')

    code = aws.create_referral_code(user_id)

    return jsonify({'code': code})



@app.route('/api/referrals/use', methods=['POST'])

def api_use_referral_code():

    payload = request.json or {}

    new_user_id = payload.get('userId')

    code = payload.get('code', '').strip().upper()

    

    if not new_user_id or not code:

        return jsonify({'error': 'userId and code required'}), 400

    

    if aws.use_referral_code(new_user_id, code):

        return jsonify({'status': 'applied'})

    return jsonify({'error': 'invalid code'}), 400





if __name__ == '__main__':

    # Ensure login background is available under static/images/login-bg.png

    def ensure_login_bg():

        project_root = os.path.dirname(__file__)

        project_images = os.path.join(project_root, 'images')

        static_images = os.path.join(project_root, 'static', 'images')

        try:

            os.makedirs(static_images, exist_ok=True)

            if os.path.isdir(project_images):

                # pick first PNG in the project-level images folder

                pngs = [p for p in os.listdir(project_images) if p.lower().endswith('.png')]

                if pngs:

                    src = os.path.join(project_images, pngs[0])

                    dst = os.path.join(static_images, 'login-bg.png')

                    if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):

                        shutil.copy2(src, dst)

        except Exception as _:

            pass



    ensure_login_bg()

    port = int(os.environ.get('PORT', 5000))

    app.run(host='0.0.0.0', port=port, debug=True)

