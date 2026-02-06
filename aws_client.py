import os
import json
import uuid
from datetime import datetime
import requests

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except Exception:
    boto3 = None

try:
    from groq import Groq
except Exception:
    Groq = None

DATA_FILE = os.path.join(os.path.dirname(__file__), 'data', 'store.json')


class AwsClient:
    def __init__(self):
        self.region = os.environ.get('AWS_REGION', 'us-east-1')
        self.dynamodb_table = os.environ.get('DDB_TABLE', 'VCC_Roadmaps')
        self.sns_topic = os.environ.get('SNS_TOPIC_ARN')
        self.groq_api_key = os.environ.get('GROQ_API_KEY')
        self.groq_client = None
        if Groq and self.groq_api_key:
            try:
                self.groq_client = Groq(api_key=self.groq_api_key)
            except Exception:
                self.groq_client = None

        if boto3:
            try:
                self.ddb = boto3.resource('dynamodb', region_name=self.region)
                self.sns = boto3.client('sns', region_name=self.region)
                # Table object may not exist in every account; methods handle fallbacks
                self.table = self.ddb.Table(self.dynamodb_table)
            except Exception:
                self.ddb = None
                self.sns = None
                self.table = None
        else:
            self.ddb = None
            self.sns = None
            self.table = None

    # Local store helpers
    def _read_store(self):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {'users': [], 'roadmaps': []}

    def _write_store(self, data):
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    def save_user_profile(self, item):
        if self.table:
            try:
                self.table.put_item(Item=item)
                return True
            except Exception:
                pass

        store = self._read_store()
        existing = None
        users = []
        for u in store.get('users', []):
            if u.get('userId') == item.get('userId'):
                existing = u
            else:
                users.append(u)

        # Merge profile updates into existing user record so we don't lose
        # credentials fields like email/passwordHash/createdAt.
        merged = {}
        if isinstance(existing, dict):
            merged.update(existing)
        if isinstance(item, dict):
            merged.update(item)
            if isinstance(existing, dict) and isinstance(existing.get('profile'), dict) and isinstance(item.get('profile'), dict):
                merged_profile = dict(existing.get('profile') or {})
                merged_profile.update(item.get('profile') or {})
                merged['profile'] = merged_profile

        users.append(merged)
        store['users'] = users
        self._write_store(store)
        return True

    # User management
    def create_user(self, email, password, profile=None):
        user_id = str(uuid.uuid4())
        user = {'userId': user_id, 'email': email, 'passwordHash': password, 'profile': profile or {}, 'createdAt': datetime.utcnow().isoformat()}
        store = self._read_store()
        users = store.get('users', [])
        users = [u for u in users if u.get('email') != email]
        users.append(user)
        store['users'] = users
        self._write_store(store)
        return user

    def get_user_by_email(self, email):
        store = self._read_store()
        for u in store.get('users', []):
            if u.get('email') == email:
                return u
        return None

    def get_user(self, user_id):
        store = self._read_store()
        for u in store.get('users', []):
            if u.get('userId') == user_id:
                return u
        return None

    # Activity tracking
    def record_activity(self, user_id, event_type, metadata=None):
        store = self._read_store()
        events = store.get('events', [])
        ev = {'userId': user_id, 'eventType': event_type, 'metadata': metadata or {}, 'timestamp': datetime.utcnow().isoformat()}
        events.append(ev)
        store['events'] = events
        self._write_store(store)
        return True

    def list_activities(self, user_id):
        store = self._read_store()
        return [e for e in store.get('events', []) if e.get('userId') == user_id]

    # Activities storage (suggested and user-tracked)
    def list_user_activities(self, user_id):
        store = self._read_store()
        return [a for a in store.get('activities', []) if a.get('userId') == user_id]

    def complete_activity(self, user_id, activity_id):
        store = self._read_store()
        activities = store.get('activities', [])
        changed = False
        for a in activities:
            if a.get('userId') == user_id and a.get('activityId') == activity_id:
                a['status'] = 'completed'
                a['completedAt'] = datetime.utcnow().isoformat()
                changed = True
        if changed:
            store['activities'] = activities
            self._write_store(store)
        return changed

    # Quiz retrieval and grading based on role and level
    def _sample_quiz(self, role, level, variant=1):
        role = (role or 'default').lower()
        level = (level or 'basic').lower()
        variant = (variant or 1)
        
        # Comprehensive quizzes for many professions with MULTIPLE question sets per level
        quizzes = {
            'teacher': {
                'basic': [
                    # Variant 1
                    {
                        'title': 'Teaching Foundations Quiz - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'Which of these is an example of formative assessment?', 'choices': ['Final semester exam','Exit ticket taken at end of class','Annual standardized test'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is scaffolding in teaching?', 'choices': ['Removing student support gradually','Building support and then removing it gradually','Avoiding student engagement'], 'answer': 1},
                            {'id': 'q3', 'text': 'Which classroom management technique is most effective?', 'choices': ['Strict punishment','Clear rules and positive reinforcement','Ignoring misbehavior'], 'answer': 1},
                            {'id': 'q4', 'text': 'What does differentiation mean?', 'choices': ['Teaching everyone the same way','Adjusting instruction for diverse learner needs','Using only one teaching method'], 'answer': 1},
                            {'id': 'q5', 'text': 'How do you encourage student participation?', 'choices': ['Call only on raised hands','Use varied questioning techniques and wait time','Only give multiple choice'], 'answer': 1}
                        ]
                    },
                    # Variant 2
                    {
                        'title': 'Teaching Foundations Quiz - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is the purpose of learning objectives?', 'choices': ['To confuse students','To guide instruction and assessment','To waste class time'], 'answer': 1},
                            {'id': 'q2', 'text': 'Which is a constructivist approach?', 'choices': ['Lecture only','Students build knowledge actively','Passive listening'], 'answer': 1},
                            {'id': 'q3', 'text': 'How often should you provide feedback?', 'choices': ['Never','Regularly and timely','Only at year end'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is Bloom\'s taxonomy used for?', 'choices': ['Student names','Levels of cognitive complexity','School budgets'], 'answer': 1},
                            {'id': 'q5', 'text': 'How can you create an inclusive classroom?', 'choices': ['Ignore differences','Acknowledge and support all learners','Exclude struggling students'], 'answer': 1}
                        ]
                    },
                    # Variant 3
                    {
                        'title': 'Teaching Foundations Quiz - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is the flipped classroom model?', 'choices': ['Students sit upside down','Content delivered at home, practice in class','Only for advanced classes'], 'answer': 1},
                            {'id': 'q2', 'text': 'Why is cultural competence important in teaching?', 'choices': ['Not important','Helps connect with all students','Only for diversity day'], 'answer': 1},
                            {'id': 'q3', 'text': 'What should lesson plans include?', 'choices': ['Just activities','Objectives, activities, and assessment','Only timing'], 'answer': 1},
                            {'id': 'q4', 'text': 'How do you handle disruptive behavior?', 'choices': ['Ignore it','Address privately with empathy','Humiliate publicly'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is cooperative learning?', 'choices': ['Students sit together silently','Structured group work for achievement','Only group projects'], 'answer': 1}
                        ]
                    },
                    # Variant 4
                    {
                        'title': 'Teaching Foundations Quiz - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What does backward design mean?', 'choices': ['Teach without planning','Start with objectives, work backward','Only for new teachers'], 'answer': 1},
                            {'id': 'q2', 'text': 'How do standardized tests fit in assessment?', 'choices': ['They are the only assessment','One tool among many','Assessment is unnecessary'], 'answer': 1},
                            {'id': 'q3', 'text': 'What builds positive classroom culture?', 'choices': ['Strictness alone','Trust, respect, and consistency','Favoritism'], 'answer': 1},
                            {'id': 'q4', 'text': 'How can technology enhance learning?', 'choices': ['Replace teachers','Support and personalize learning','Technology is always bad'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is metacognition?', 'choices': ['A disease','Thinking about one\'s own thinking','Not relevant to teaching'], 'answer': 1}
                        ]
                    },
                    # Variant 5
                    {
                        'title': 'Teaching Foundations Quiz - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'How do you support visual learners?', 'choices': ['Give them only text','Use diagrams, charts, and videos','Say it once only'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is a learning gap?', 'choices': ['A hole in the classroom','Difference between current and desired performance','Irrelevant concept'], 'answer': 1},
                            {'id': 'q3', 'text': 'How should you respond to wrong answers?', 'choices': ['Humiliate the student','Use as teachable moment','Ignore completely'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is intrinsic motivation?', 'choices': ['Grades only','Internal drive to learn','Money rewards'], 'answer': 1},
                            {'id': 'q5', 'text': 'Why are clear expectations important?', 'choices': ['Students like surprises','Reduces confusion and behavior issues','Expectations are limiting'], 'answer': 1}
                        ]
                    }
                ],
                'intermediate': [
                    {
                        'title': 'Teaching Strategies for Diverse Learners - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What is Universal Design for Learning (UDL)?', 'choices': ['One teaching method fits all','Designing for all learners from the start','Advanced technology only'], 'answer': 1},
                            {'id': 'q2', 'text': 'How can you support English Language Learners?', 'choices': ['Speak louder','Use visuals, gestures, and simplified language','Ignore language barriers'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is the benefit of cooperative learning?', 'choices': ['Less work for teachers','Develops collaboration and peer learning','Students learn nothing'], 'answer': 1},
                            {'id': 'q4', 'text': 'How do you differentiate for advanced learners?', 'choices': ['More homework','Provide extension tasks and challenges','Treat everyone equally'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Teaching Strategies for Diverse Learners - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is response to intervention (RTI)?', 'choices': ['Ignoring needs','Tiered support based on performance','Only for special education'], 'answer': 1},
                            {'id': 'q2', 'text': 'How should you adapt for students with IEPs?', 'choices': ['Ignore the IEP','Follow IEP goals and accommodations','Lower all expectations'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is peer tutoring?', 'choices': ['Paid tutors only','Students teaching students','Not effective'], 'answer': 1},
                            {'id': 'q4', 'text': 'How do you create a safe space for questions?', 'choices': ['Discourage asking','Praise all questions equally','Never answer questions'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Teaching Strategies for Diverse Learners - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is the impact of poverty on learning?', 'choices': ['None','Can affect academic outcomes','Always causes failure'], 'answer': 1},
                            {'id': 'q2', 'text': 'How do you build on student strengths?', 'choices': ['Focus only on weaknesses','Identify and leverage individual strengths','Everyone has same strengths'], 'answer': 1},
                            {'id': 'q3', 'text': 'What does asset-based teaching mean?', 'choices': ['Only for wealthy students','Focusing on what students bring to class','Ignoring student backgrounds'], 'answer': 1},
                            {'id': 'q4', 'text': 'How important is family engagement?', 'choices': ['Not important','Critical for student success','Only for elementary'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Teaching Strategies for Diverse Learners - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What is restorative justice in schools?', 'choices': ['Punishment only','Building relationships and accountability','Ignoring conflicts'], 'answer': 1},
                            {'id': 'q2', 'text': 'How do you address implicit bias?', 'choices': ['Ignore bias','Self-reflect and adjust practices','Bias doesn\'t exist'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is culturally responsive teaching?', 'choices': ['Ignoring culture','Honoring and integrating student cultures','One size fits all'], 'answer': 1},
                            {'id': 'q4', 'text': 'How do you support students experiencing trauma?', 'choices': ['Push harder','Use empathy and therapeutic approaches','That\'s not the teacher\'s role'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Teaching Strategies for Diverse Learners - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'What is social-emotional learning (SEL)?', 'choices': ['Just grades','Developing interpersonal and intrapersonal skills','Not the teacher\'s job'], 'answer': 1},
                            {'id': 'q2', 'text': 'How do you create equitable assessments?', 'choices': ['Same for everyone','Remove bias and provide accommodations','Assessments are unnecessary'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is the impact of stereotype threat?', 'choices': ['Doesn\'t exist','Can negatively affect performance','Only affects minorities'], 'answer': 1},
                            {'id': 'q4', 'text': 'How should you handle language differences?', 'choices': ['Correct constantly','Use as asset and support','Ignore completely'], 'answer': 1}
                        ]
                    }
                ],
                'advanced': [
                    {
                        'title': 'Advanced Pedagogical Practices - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'Which approach promotes deeper learning?', 'choices': ['Rote memorization','Project-based learning with reflection','Passive listening'], 'answer': 1},
                            {'id': 'q2', 'text': 'How do you assess higher-order thinking?', 'choices': ['Multiple choice only','Open-ended tasks, portfolios, and performance assessments','Avoid challenging questions'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is Vygotsky\'s zone of proximal development?', 'choices': ['No relevance','Space between current and potential ability','Same as current ability'], 'answer': 1},
                            {'id': 'q4', 'text': 'How do you use formative assessment effectively?', 'choices': ['Once per year','Continuously to inform instruction','Never needed'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced Pedagogical Practices - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is inquiry-based learning?', 'choices': ['Teacher gives all answers','Students investigate and discover','Students are passive'], 'answer': 1},
                            {'id': 'q2', 'text': 'How do you measure learning outcomes?', 'choices': ['Guess','Use valid, reliable assessments','Only grades count'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is the role of transfer in learning?', 'choices': ['Not important','Applying learning to new contexts','Learning is isolated'], 'answer': 1},
                            {'id': 'q4', 'text': 'How should curriculum be designed?', 'choices': ['Chronologically only','Around standards and real-world connections','Random selection'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced Pedagogical Practices - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is the impact of teacher expectations on students?', 'choices': ['None','Significant (Pygmalion effect)','Negative always'], 'answer': 1},
                            {'id': 'q2', 'text': 'How do you use data to improve instruction?', 'choices': ['Ignore data','Analyze and adjust practices','Data is irrelevant'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is critical pedagogy?', 'choices': ['Just criticism','Teaching students to question and think critically','No critical thinking'], 'answer': 1},
                            {'id': 'q4', 'text': 'How important is professional learning?', 'choices': ['Not important','Continuous to stay current','Only when required'], 'answer': 1}
                        ]
                    }
                ]
            },
            'software engineer': {
                'basic': [
                    {
                        'title': 'Software Development Fundamentals - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What does HTTP stand for?', 'choices': ['HyperText Transfer Protocol','Hyperlink Transfer Text Protocol','High Transfer Text Protocol'], 'answer': 0},
                            {'id': 'q2', 'text': 'Which data structure uses LIFO?', 'choices': ['Queue','Stack','Array'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is version control?', 'choices': ['Managing code changes','Deleting old files','Storing passwords'], 'answer': 0},
                            {'id': 'q4', 'text': 'What is an API?', 'choices': ['Advanced Programming Interface','Application Programming Interface','Application Process Initiative'], 'answer': 1},
                            {'id': 'q5', 'text': 'What does DRY mean?', 'choices': ['Dry code','Don\'t Repeat Yourself','Delete Random Yields'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is a variable?', 'choices': ['A fixed value','Container for data','A function'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Software Development Fundamentals - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is JSON?', 'choices': ['A database','JavaScript Object Notation','A programming language'], 'answer': 1},
                            {'id': 'q2', 'text': 'What does REST stand for?', 'choices': ['Remaining Energy','Representational State Transfer','Resource State Technology'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is a loop?', 'choices': ['Round shape','Repeated execution of code','A type of variable'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is the purpose of comments?', 'choices': ['Waste space','Explain code','Required for all code'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is a function?', 'choices': ['Only for math','Reusable block of code','Type of variable'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is debugging?', 'choices': ['Adding bugs','Finding and fixing errors','Deleting code'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Software Development Fundamentals - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is Git?', 'choices': ['A type of code','Version control system','Programming language'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is an algorithm?', 'choices': ['A math concept only','Step-by-step procedure to solve a problem','Type of loop'], 'answer': 1},
                            {'id': 'q3', 'text': 'What does IDE stand for?', 'choices': ['Integrated Development Environment','Internal Data Exchange','Internet Design Engine'], 'answer': 0},
                            {'id': 'q4', 'text': 'What is a database?', 'choices': ['Base of a desk','Organized collection of data','Type of code'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is string concatenation?', 'choices': ['Combining strings','Deleting text','Reversing code'], 'answer': 0},
                            {'id': 'q6', 'text': 'What is abstraction?', 'choices': ['Complex thinking','Hiding implementation details','Mathematical concept'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Software Development Fundamentals - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What is object-oriented programming?', 'choices': ['Only for objects','Organizing code into classes and objects','Outdated approach'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is encapsulation?', 'choices': ['Storing in capsules','Bundling data and methods together','Encryption'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is inheritance?', 'choices': ['Money only','Classes inheriting properties from others','Getting rich'], 'answer': 1},
                            {'id': 'q4', 'text': 'What does HTTPS provide?', 'choices': ['Faster speed','Secure communication','More data'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is a library in programming?', 'choices': ['Place to read books','Collection of reusable code','Database only'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is a branch in Git?', 'choices': ['Tree part','Separate line of development','Type of tree'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Software Development Fundamentals - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'What is the purpose of testing?', 'choices': ['Find bugs early','Waste time','Only for finished code'], 'answer': 0},
                            {'id': 'q2', 'text': 'What is syntax?', 'choices': ['Meaning','Grammar and rules of a language','Comments'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is a boolean?', 'choices': ['A name','True or false value','Equation'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is a conditional statement?', 'choices': ['Always true','Makes decisions based on conditions','Loop'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is documentation?', 'choices': ['Just comments','Explains code and how to use it','Not important'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is a array?', 'choices': ['Mathematical shape','Ordered collection of items','Type of database'], 'answer': 1}
                        ]
                    }
                ],
                'intermediate': [
                    {
                        'title': 'Intermediate Software Engineering - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What is unit testing?', 'choices': ['Testing entire app','Testing small components in isolation','Testing only UI'], 'answer': 1},
                            {'id': 'q2', 'text': 'Design patterns help with:', 'choices': ['Writing HTML','Solving recurring design problems','Database only'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is refactoring?', 'choices': ['Rewriting from scratch','Improving code without changing functionality','Deleting code'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is the purpose of debugging?', 'choices': ['Add bugs','Find and fix errors','Delete code'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is continuous integration?', 'choices': ['Rarely merging code','Frequently integrating and testing code','Never testing'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Intermediate Software Engineering - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is MVC pattern?', 'choices': ['Random letters','Model-View-Controller separation','Only for web'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is code review?', 'choices': ['Reading comments only','Peer examining code changes','Not necessary'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is the purpose of logging?', 'choices': ['Environmental','Record events for debugging','Unnecessary'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is error handling?', 'choices': ['Ignoring errors','Managing and recovering from errors','Only for warnings'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is code smell?', 'choices': ['Literal smell','Indication of deeper problems','Not important'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Intermediate Software Engineering - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is polymorphism?', 'choices': ['Many shapes only','Objects behaving differently','Math concept'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is a module?', 'choices': ['Education only','Self-contained unit of code','Type of library'], 'answer': 1},
                            {'id': 'q3', 'text': 'What does DRY principle prevent?', 'choices': ['Dry code','Code duplication','Writing code'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is the purpose of middleware?', 'choices': ['No purpose','Processing between request and response','Just logging'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is agile development?', 'choices': ['Fast coding','Iterative development with feedback','Waterfall method'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Intermediate Software Engineering - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What is integration testing?', 'choices': ['Testing one component','Testing multiple components together','Only unit testing matters'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is scalability?', 'choices': ['Using scales','Handling growth in users/data','Not important'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is the KISS principle?', 'choices': ['A salute','Keep It Simple Stupid','Complex is better'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is dependency injection?', 'choices': ['Injecting code','Passing dependencies as parameters','Not needed'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is the purpose of caching?', 'choices': ['No purpose','Improving performance','Slowing things down'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Intermediate Software Engineering - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'What is a REST API?', 'choices': ['Sleeping API','API following REST principles','Database query'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is Docker used for?', 'choices': ['Waterproof code','Containerizing applications','File storage'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is security in code?', 'choices': ['Optional','Protecting against vulnerabilities','Not developer\'s job'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is technical debt?', 'choices': ['Money owed','Accumulated suboptimal code','Not real'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is pair programming?', 'choices': ['Two people guessing','Two developers working together','Slow method'], 'answer': 1}
                        ]
                    }
                ],
                'advanced': [
                    {
                        'title': 'Advanced Software Architecture - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What is the purpose of SOLID principles?', 'choices': ['Making code solid','Writing maintainable code','For beginners only'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is microservices architecture?', 'choices': ['Small services only','Breaking app into independent services','Monolithic'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is system design?', 'choices': ['Just UI','Planning scalable, reliable systems','Not important'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is DevOps?', 'choices': ['Developer operations only','Bridging dev and operations','Unnecessary'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced Software Architecture - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is API gateway?', 'choices': ['Entrance door','Central entry point for APIs','Not needed'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is eventual consistency?', 'choices': ['Always consistent','Data eventually becomes consistent','No consistency'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is load balancing?', 'choices': ['Equal weights','Distributing traffic across servers','Unnecessary'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is a database cluster?', 'choices': ['Group of databases','Connected database systems','Single server'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced Software Architecture - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is sharding?', 'choices': ['Breaking things','Partitioning data across servers','Combining data'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is CAP theorem?', 'choices': ['Hat acronym','Consistency, Availability, Partition tolerance tradeoff','Not applicable'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is circuit breaker pattern?', 'choices': ['Electrical only','Preventing cascading failures','Not needed'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is rate limiting?', 'choices': ['Speed limits','Controlling request frequency','Not important'], 'answer': 1}
                        ]
                    }
                ]
            },
            'data analyst': {
                'basic': [
                    {
                        'title': 'Data Analysis Fundamentals - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'SQL is used for:', 'choices': ['Web design','Database queries','Graphics'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is a primary key?', 'choices': ['Optional field','Unique identifier','Password'], 'answer': 1},
                            {'id': 'q3', 'text': 'Data visualization helps by:', 'choices': ['Making unreadable','Communicating patterns','Storage only'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is a dataset?', 'choices': ['Single number','Collection of data','Graph'], 'answer': 1},
                            {'id': 'q5', 'text': 'What does ETL stand for?', 'choices': ['Extract Transfer Load','Extract, Transform, Load','Edit Template Language'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is data quality?', 'choices': ['Unimportant','Accuracy and completeness of data','Only for big data'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Data Analysis Fundamentals - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is a data warehouse?', 'choices': ['Physical location','Centralized repository','Only for large companies'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is an index in databases?', 'choices': ['Book index only','Structure for faster queries','Not useful'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is OLTP?', 'choices': ['Type of data','Online Transaction Processing','Not relevant'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is a pivot table?', 'choices': ['Just rotation','Reorganizing data for analysis','Not useful'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is data normalization?', 'choices': ['Making normal','Organizing data efficiently','Only for large databases'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is aggregation?', 'choices': ['Just combining','Summarizing data (sum, avg, etc.)','Not useful'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Data Analysis Fundamentals - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is a foreign key?', 'choices': ['Outside USA','Link between tables','Type of field'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is data modeling?', 'choices': ['Runway models','Designing data structures','Not important'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is exploratory data analysis?', 'choices': ['Travel only','Initial data investigation','Not needed'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is sampling?', 'choices': ['Tasting food','Taking subset of data','Not valid'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is filtering?', 'choices': ['Air filter only','Selecting specific data','Not useful'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is a dashboard?', 'choices': ['Car part','Visual representation of metrics','Only numbers'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Data Analysis Fundamentals - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What is descriptive analytics?', 'choices': ['Only describing','Describing what happened','Predicting'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is an outlier?', 'choices': ['Outside country','Unusual data point','Not important'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is trend analysis?', 'choices': ['Fashion only','Identifying patterns over time','Not relevant'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is cross-tabulation?', 'choices': ['Across tables only','Two-way analysis','Not used'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is data granularity?', 'choices': ['Sand texture','Level of detail in data','Not important'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is a KPI?', 'choices': ['Type of fruit','Key Performance Indicator','Math term'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Data Analysis Fundamentals - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'What is data integrity?', 'choices': ['Honesty','Accuracy and consistency','Only for backups'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is a query?', 'choices': ['Question only','Request for data','Type of database'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is data profiling?', 'choices': ['Criminal only','Examining data characteristics','Not needed'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is metadata?', 'choices': ['Metal data','Data about data','Not useful'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is a report?', 'choices': ['Tattling only','Documented findings','Just numbers'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is business intelligence?', 'choices': ['Only intelligence','Using data for business decisions','Not applicable'], 'answer': 1}
                        ]
                    }
                ],
                'intermediate': [
                    {
                        'title': 'Intermediate Data Analytics - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What is correlation vs causation?', 'choices': ['Same','Different - causation implies relationship','Not important'], 'answer': 1},
                            {'id': 'q2', 'text': 'Which tool for visualization?', 'choices': ['Notepad','Tableau, Power BI, Python','Word'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is data cleaning?', 'choices': ['Deleting all','Removing errors and inconsistencies','Ignore bad data'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is joins in SQL?', 'choices': ['Only combining','Merging tables on conditions','Not needed'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is group by?', 'choices': ['Physical groups','Aggregating by categories','Not useful'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Intermediate Data Analytics - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is predictive analytics?', 'choices': ['Just guessing','Using data to forecast','Only for weather'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is segmentation?', 'choices': ['Cutting only','Dividing data into groups','Not useful'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is cohort analysis?', 'choices': ['Only age','Analyzing groups over time','Not relevant'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is AB testing?', 'choices': ['Just letters','Comparing versions','Only for websites'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is funnel analysis?', 'choices': ['Funnels only','Tracking progression through steps','Not important'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Intermediate Data Analytics - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is statistical significance?', 'choices': ['Important stats','Results not due to chance','All results matter'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is confidence interval?', 'choices': ['Believing in self','Range of estimated values','Exact value'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is distribution?', 'choices': ['Spreading','Pattern of data values','Not important'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is hypothesis testing?', 'choices': ['Just guessing','Testing predictions statistically','Not scientific'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is variance in statistics?', 'choices': ['Variety only','Spread of data','Same as mean'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Intermediate Data Analytics - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What is the purpose of data governance?', 'choices': ['No purpose','Managing data quality and compliance','For big companies'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is a star schema?', 'choices': ['Only stars','Dimensional data model','Not useful'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is incremental loading?', 'choices': ['Slowly only','Loading new data efficiently','All at once'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is data reconciliation?', 'choices': ['Making peace','Verifying data consistency','Not needed'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is the purpose of SLA?', 'choices': ['Not important','Defining service level expectations','Only IT'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Intermediate Data Analytics - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'What is RFM analysis?', 'choices': ['Random letters','Recency, Frequency, Monetary analysis','Not used'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is churn analysis?', 'choices': ['Only butter','Analyzing customer loss','Not important'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is data retention?', 'choices': ['Memory only','Keeping historical data','Not needed'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is data lineage?', 'choices': ['Only family tree','Tracking data origin and flow','Not useful'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is data versioning?', 'choices': ['Not important','Managing data versions over time','Only for backups'], 'answer': 1}
                        ]
                    }
                ],
                'advanced': [
                    {
                        'title': 'Advanced Data Science - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'Machine Learning purpose?', 'choices': ['All tasks','Predictive modeling and patterns','Replacing humans'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is overfitting?', 'choices': ['Too much fitting','Fitting too well to training data','Underfitting'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is feature engineering?', 'choices': ['Only engineering','Creating useful variables','Not necessary'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is cross-validation?', 'choices': ['Crossing validation','Testing model generalization','Only train/test'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced Data Science - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is dimensionality reduction?', 'choices': ['Making smaller','Reducing features while keeping info','Not useful'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is regularization?', 'choices': ['Just normalizing','Preventing overfitting','Not needed'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is hyperparameter?', 'choices': ['Parameter above','Model configuration settings','Not important'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is ensemble method?', 'choices': ['Music only','Combining multiple models','Single model better'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced Data Science - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is clustering?', 'choices': ['Just grouping','Unsupervised grouping of similar items','Only supervised'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is ROC curve?', 'choices': ['Moving curve','Evaluating classification performance','Only for ML'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is feature selection?', 'choices': ['Choosing features','Selecting most relevant features','All features needed'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is class imbalance?', 'choices': ['Not a problem','Unequal class distribution','Only in classification'], 'answer': 1}
                        ]
                    }
                ]
            },
            'ux designer': {
                'basic': [
                    {
                        'title': 'UX Design Fundamentals - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What does UX stand for?', 'choices': ['User Experience','Ultimate X-ray','Universal Xylophone'], 'answer': 0},
                            {'id': 'q2', 'text': 'User research helps by:', 'choices': ['Guessing needs','Understanding real needs','Ignoring users'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is wireframing?', 'choices': ['Adding colors','Low-fidelity layout','Final design'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is prototyping?', 'choices': ['Final product','Interactive mockup','Document'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is usability?', 'choices': ['Beauty','Ease of use','Colors'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is accessibility?', 'choices': ['Location','Enabling use for all','Optional'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'UX Design Fundamentals - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is UX vs UI?', 'choices': ['Same thing','UX is experience, UI is interface','UI is important only'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is a user journey?', 'choices': ['Travel only','Path user takes','Just landing page'], 'answer': 1},
                            {'id': 'q3', 'text': 'What are user personas?', 'choices': ['Fictional characters','Representations of users','Only marketing'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is empathy mapping?', 'choices': ['Just maps','Understanding user emotions and thoughts','Not needed'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is interaction design?', 'choices': ['Just UI','How users interact with products','Only visual'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is information architecture?', 'choices': ['Building only','Organizing content structure','Just layout'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'UX Design Fundamentals - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is a use case?', 'choices': ['Court case','Description of user goal','Legal case'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is task flow?', 'choices': ['Water flow','Steps to complete goal','Just buttons'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is cognitive load?', 'choices': ['Mental weight','Mental effort required','Only memory'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is affordance?', 'choices': ['Price only','Visual cues for interaction','Not important'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is gestalt principle?', 'choices': ['Language','Visual grouping principles','Not relevant'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is feedback in UX?', 'choices': ['Opinions only','System response to user','Just comments'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'UX Design Fundamentals - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What is information scent?', 'choices': ['Smell only','Indicating content relevance','Not real'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is progressive disclosure?', 'choices': ['Revealing slowly','Showing info as needed','Show everything'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is mental model?', 'choices': ['Fashion model','How users think about system','Not important'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is heuristic?', 'choices': ['Medical term','Rule of thumb','Not useful'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is consistency?', 'choices': ['Never changes','Predictable patterns','Variety better'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is error prevention?', 'choices': ['No errors','Stopping problems before occurring','Accept errors'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'UX Design Fundamentals - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'What is responsive design?', 'choices': ['Talking back','Adapting to screen sizes','Only desktop'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is mobile-first?', 'choices': ['Phones only','Designing mobile before desktop','Desktop first'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is dark mode?', 'choices': ['Sad theme','Low-light interface option','Never needed'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is micro-interaction?', 'choices': ['Small details','Small animations and feedback','Not important'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is onboarding?', 'choices': ['Getting on board','Initial user experience','Not needed'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is delight in UX?', 'choices': ['Happy only','Exceeding user expectations','Unnecessary'], 'answer': 1}
                        ]
                    }
                ],
                'intermediate': [
                    {
                        'title': 'UX Strategy & Usability - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What is usability testing?', 'choices': ['Guessing','Observing real users','Only focus groups'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is A/B testing in UX?', 'choices': ['Letter test','Comparing versions','Only for ads'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is heuristic evaluation?', 'choices': ['Medical only','Expert review against guidelines','Not useful'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is SUS score?', 'choices': ['Acronym only','System Usability Scale','Not important'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is task completion rate?', 'choices': ['Tasks only','Percentage successfully completing','Not a metric'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'UX Strategy & Usability - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is card sorting?', 'choices': ['Playing cards','User-driven organization method','Not useful'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is tree testing?', 'choices': ['Climbing trees','Testing information structure','Only wireframes'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is preference testing?', 'choices': ['Personal preferences only','Testing which design users prefer','Not scientific'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is user retention?', 'choices': ['Memory only','Keeping users engaged','Not important'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is conversion optimization?', 'choices': ['Religious only','Improving user action rates','Not relevant'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'UX Strategy & Usability - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is product-market fit?', 'choices': ['Exact size','Product meeting market needs','Irrelevant'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is competitive analysis?', 'choices': ['Just competitors','Understanding competitor products','Not needed'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is opportunity mapping?', 'choices': ['Treasure map','Identifying user needs gaps','Not useful'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is design thinking?', 'choices': ['Just thinking','Problem-solving methodology','Only art'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is value proposition?', 'choices': ['Price only','Why users choose product','Not important'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'UX Strategy & Usability - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What is ecosystem mapping?', 'choices': ['Environment only','Understanding all touchpoints','Just product'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is stakeholder mapping?', 'choices': ['Stakes only','Identifying key people','Not needed'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is iteration in design?', 'choices': ['Repeating only','Continuous improvement cycles','Perfect first time'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is MVP?', 'choices': ['Sports award','Minimum Viable Product','Not relevant'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is de-risking?', 'choices': ['No risks','Reducing design risks early','Risks don\'t matter'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'UX Strategy & Usability - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'What is emotional design?', 'choices': ['Only feelings','Creating emotional connections','Not important'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is persuasive design?', 'choices': ['Forcing choices','Guiding users toward actions','Manipulative'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is dark patterns?', 'choices': ['Evil design','Deceptive design tricks','Not real'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is inclusive design?', 'choices': ['Including everyone','Designing for diverse abilities','Only disabled'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is sustainable UX?', 'choices': ['Environmental only','Long-term product health','Not relevant'], 'answer': 1}
                        ]
                    }
                ],
                'advanced': [
                    {
                        'title': 'Advanced UX & Design Systems - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What is a design system?', 'choices': ['Just colors','Reusable components and guidelines','Only for large teams'], 'answer': 1},
                            {'id': 'q2', 'text': 'How measure UX success?', 'choices': ['Just beauty','Metrics like completion and satisfaction','Subjective only'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is component library?', 'choices': ['Book library','Reusable UI building blocks','Not needed'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is design token?', 'choices': ['Design gift','Reusable design values','Only colors'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced UX & Design Systems - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is design debt?', 'choices': ['Money owed','Accumulated design compromises','Not real'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is accessibility audit?', 'choices': ['Accounting only','Systematic accessibility review','Not important'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is design ops?', 'choices': ['Operations only','Managing design processes','Not needed'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is research synthesis?', 'choices': ['Making up data','Combining research findings','Not scientific'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced UX & Design Systems - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is design governance?', 'choices': ['Government only','Maintaining design standards','Not needed'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is design maturity model?', 'choices': ['Age only','Assessing design capability levels','Not useful'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is user research ops?', 'choices': ['Operational only','Managing research programs','Not important'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is design thinking workshop?', 'choices': ['Just meeting','Facilitated problem-solving session','Not effective'], 'answer': 1}
                        ]
                    }
                ]
            },
            'product manager': {
                'basic': [
                    {
                        'title': 'Product Management Basics - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What is a product roadmap?', 'choices': ['Navigation only','Planned features and timeline','Just a document'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is a PM\'s role?', 'choices': ['Coding only','Guiding strategy and connecting teams','Just meetings'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is a user story?', 'choices': ['Fiction','Feature from user perspective','Just documentation'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is product-market fit?', 'choices': ['Exact size','Product satisfying demand','Always guaranteed'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is MVP?', 'choices': ['Sports award','Minimum Viable Product','Full product'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is a feature?', 'choices': ['Just cosmetic','Functionality addressing user need','Only big items'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Product Management Basics - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is market sizing?', 'choices': ['Clothing sizes','Estimating addressable market','Only for startups'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is competitive advantage?', 'choices': ['Sports only','Unique selling proposition','Not important'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is customer acquisition?', 'choices': ['Stealing customers','Getting new users','Only retention'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is retention rate?', 'choices': ['Keeping things','Percentage staying users','Only monthly'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is churn rate?', 'choices': ['Butter only','Percentage leaving users','Not important'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is pricing strategy?', 'choices': ['Cost only','Determining product cost','Not PM duty'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Product Management Basics - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is stakeholder?', 'choices': ['Stakes only','Person invested in product','Not important'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is requirements gathering?', 'choices': ['Collecting requirements','Understanding what to build','Not needed'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is product vision?', 'choices': ['Just eyesight','Long-term product direction','Not needed'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is product strategy?', 'choices': ['War planning','Plan to achieve goals','Only for big companies'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is product launch?', 'choices': ['Rocket only','Introduction to market','Just release'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is product lifecycle?', 'choices': ['Personal life','Stages from launch to sunset','Irrelevant'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Product Management Basics - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What is total addressable market?', 'choices': ['Total addresses','Maximum revenue opportunity','Irrelevant'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is product differentiation?', 'choices': ['Making different','Standing out from competitors','Not important'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is customer feedback?', 'choices': ['Compliments only','User input on product','Not important'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is product analytics?', 'choices': ['Just data','Measuring product performance','Only engineers'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is user engagement?', 'choices': ['Just interaction','Level of user involvement','Not measurable'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is product iteration?', 'choices': ['Just repeating','Continuous improvement cycles','Get it perfect first'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Product Management Basics - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'What is user onboarding?', 'choices': ['Getting on board','Initial user experience','Not needed'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is product positioning?', 'choices': ['Physical position','Market positioning strategy','Not important'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is product backlog?', 'choices': ['Unsupported','List of work items','Not organized'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is sprint planning?', 'choices': ['Running fast','Planning work iteration','Only for Agile'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is product demo?', 'choices': ['Demonstration only','Showing product to users','Just for launches'], 'answer': 1},
                            {'id': 'q6', 'text': 'What is post-launch review?', 'choices': ['After party','Analyzing launch results','Not done'], 'answer': 1}
                        ]
                    }
                ],
                'intermediate': [
                    {
                        'title': 'Product Strategy & Metrics - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'What is KPI?', 'choices': ['Type of food','Key Performance Indicator','Just a number'], 'answer': 1},
                            {'id': 'q2', 'text': 'How prioritize features?', 'choices': ['Random','Using RICE or MoSCoW','No system'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is A/B testing?', 'choices': ['Alphabet test','Comparing versions','Only marketing'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is funnel analysis?', 'choices': ['Funnels only','Tracking progression steps','Not useful'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is metrics tracking?', 'choices': ['Tracking athletes','Monitoring product metrics','Not important'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Product Strategy & Metrics - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is OKR?', 'choices': ['Acronym only','Objectives and Key Results','Just goals'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is SWOT analysis?', 'choices': ['Strength only','Strengths, Weaknesses, Opportunities, Threats','Not useful'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is customer segmentation?', 'choices': ['Cutting only','Dividing users into groups','Not useful'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is TAM/SAM/SOM?', 'choices': ['Names only','Market opportunity framework','Not relevant'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is go-to-market?', 'choices': ['Transportation','Launch and market strategy','Just release'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Product Strategy & Metrics - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is cohort analysis?', 'choices': ['Only age','Analyzing groups over time','Not relevant'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is customer lifetime value?', 'choices': ['Age only','Total profit from customer','Not measurable'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is net promoter score?', 'choices': ['Just grade','Customer loyalty metric','Not important'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is data-driven decision?', 'choices': ['No data','Decisions based on data','Just intuition'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is innovation pipeline?', 'choices': ['Plumbing only','New ideas in development','Not needed'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Product Strategy & Metrics - Set 4',
                        'questions': [
                            {'id': 'q1', 'text': 'What is market research?', 'choices': ['Just searching','Understanding market and users','Expensive only'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is product health score?', 'choices': ['Only health','Measuring overall product status','Not real'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is release management?', 'choices': ['Letting go','Coordinating product releases','Not important'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is feature deprecation?', 'choices': ['Only decreasing','Phasing out features','Never done'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is competitive intelligence?', 'choices': ['Spying only','Understanding competitor strategy','Not ethical'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Product Strategy & Metrics - Set 5',
                        'questions': [
                            {'id': 'q1', 'text': 'What is product portfolio?', 'choices': ['Art collection','Set of related products','Not important'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is ecosystem strategy?', 'choices': ['Environment only','Planning product ecosystem','Just product'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is platform thinking?', 'choices': ['Just platforms','Network effects and multi-sided','Only software'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is moonshot project?', 'choices': ['Space only','Bold innovation initiative','Unrealistic'], 'answer': 1},
                            {'id': 'q5', 'text': 'What is product sustainability?', 'choices': ['Environmental only','Long-term viability','Not relevant'], 'answer': 1}
                        ]
                    }
                ],
                'advanced': [
                    {
                        'title': 'Advanced Product Leadership - Set 1',
                        'questions': [
                            {'id': 'q1', 'text': 'Difference strategy vs roadmap?', 'choices': ['Same','Vision vs implementation','Only roadmap'], 'answer': 1},
                            {'id': 'q2', 'text': 'Handle stakeholder conflicts?', 'choices': ['Ignore','Align on goals, use data','Always say yes'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is product leadership?', 'choices': ['Just management','Guiding product direction','Only executives'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is transformation roadmap?', 'choices': ['Just travel','Roadmap for org change','Not PM job'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced Product Leadership - Set 2',
                        'questions': [
                            {'id': 'q1', 'text': 'What is platform monetization?', 'choices': ['Only money','Generating revenue model','Not relevant'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is international strategy?', 'choices': ['Travel only','Global market expansion','Only domestic'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is organizational design?', 'choices': ['Just hierarchy','Structuring teams for product','Not relevant'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is crisis management?', 'choices': ['Emergency only','Handling product incidents','Not PM'], 'answer': 1}
                        ]
                    },
                    {
                        'title': 'Advanced Product Leadership - Set 3',
                        'questions': [
                            {'id': 'q1', 'text': 'What is board management?', 'choices': ['Only boards','Communicating with leadership','Just reporting'], 'answer': 1},
                            {'id': 'q2', 'text': 'What is product culture?', 'choices': ['Just culture','Team\'s approach to product','Not PM\'s job'], 'answer': 1},
                            {'id': 'q3', 'text': 'What is talent development?', 'choices': ['Only HR','Growing product team skills','Not important'], 'answer': 1},
                            {'id': 'q4', 'text': 'What is strategic partnership?', 'choices': ['Just alliance','Collaborating for growth','Not relevant'], 'answer': 1}
                        ]
                    }
                ]
            }
        }
        
        # Normalize role to match quiz keys
        role_key = role
        for key in quizzes.keys():
            if key in role or role in key:
                role_key = key
                break
        
        # Try to get the quiz, or return generic
        if role_key in quizzes and level in quizzes[role_key]:
            quiz_list = quizzes[role_key][level]
            # Select variant based on number, cycling if needed
            quiz_idx = (variant - 1) % len(quiz_list)
            return quiz_list[quiz_idx]
        elif role_key in quizzes:
            # Return first available level
            available_levels = list(quizzes[role_key].keys())
            if available_levels:
                quiz_list = quizzes[role_key][available_levels[0]]
                quiz_idx = (variant - 1) % len(quiz_list)
                return quiz_list[quiz_idx]
        
        # Default/generic fallback
        return {
            'title': f'{role.title()} - {level.title()} Quiz (Variant {variant})',
            'questions': [
                {'id': 'q1', 'text': f'What is an important skill in {role}?', 'choices': ['Practice and learning','Ignoring fundamentals','Avoiding challenges'], 'answer': 0},
                {'id': 'q2', 'text': f'How can you improve your {role} skills?', 'choices': ['Continuous practice','Never trying anything new','Avoiding feedback'], 'answer': 0},
                {'id': 'q3', 'text': f'Why is professional development important in {role}?', 'choices': ['Not important','Staying current with trends','Only for beginners'], 'answer': 1},
                {'id': 'q4', 'text': f'What tools are essential for {role}?', 'choices': ['None needed','Industry-standard tools','Only one tool'], 'answer': 1},
                {'id': 'q5', 'text': f'What makes someone successful in {role}?', 'choices': ['Just luck','Continuous learning and practice','Natural talent only'], 'answer': 1}
            ]
        }

    def get_quiz_for_activity(self, activity_id):
        store = self._read_store()
        for a in store.get('activities', []):
            if a.get('activityId') == activity_id:
                role = a.get('role') or 'default'
                level = a.get('level') or 'basic'
                variant = a.get('quizVariant', 1)
                quiz = self._sample_quiz(role, level, variant)
                return {'activity': a, 'quiz': quiz}
        return None

    def grade_quiz(self, activity_id, answers_map):
        qa = self.get_quiz_for_activity(activity_id)
        if not qa:
            return None
        quiz = qa['quiz']
        questions = quiz.get('questions', [])
        correct = 0
        for q in questions:
            qid = q['id']
            if qid in answers_map and int(answers_map[qid]) == int(q.get('answer', -1)):
                correct += 1
        score = int((correct / max(1, len(questions))) * 100)
        # persist result on activity
        store = self._read_store()
        for a in store.get('activities', []):
            if a.get('activityId') == activity_id:
                a['lastScore'] = score
                a['status'] = 'completed' if score >= 70 else 'pending'
                a['completedAt'] = datetime.utcnow().isoformat()
        self._write_store(store)
        return {'score': score, 'total': len(questions)}

    def get_leaderboard(self, top_n=10):
        store = self._read_store()
        activities = [a for a in store.get('activities', []) if a.get('status') == 'completed' and a.get('lastScore') is not None]
        # aggregate by user
        agg = {}
        for a in activities:
            uid = a.get('userId')
            agg.setdefault(uid, {'total': 0, 'count': 0})
            agg[uid]['total'] += int(a.get('lastScore', 0))
            agg[uid]['count'] += 1
        rows = []
        for uid, v in agg.items():
            avg = int(v['total'] / v['count']) if v['count'] else 0
            # try to get user name/email
            user = None
            for u in store.get('users', []):
                if u.get('userId') == uid:
                    user = u
                    break
            display = (user.get('profile', {}).get('fullName') or user.get('profile', {}).get('name') if user else None) or (user.get('email') if user else uid)
            rows.append({'userId': uid, 'display': display, 'avgScore': avg, 'completed': v['count']})
        rows.sort(key=lambda r: r['avgScore'], reverse=True)
        return rows[:top_n]

    def list_roadmaps_for_user(self, user_id):
        store = self._read_store()
        return [r for r in store.get('roadmaps', []) if r.get('userId') == user_id]

    def create_activities_for_role(self, user_id, role):
        # create suggested actionable activities based on role
        role = (role or '').lower()
        
        # Normalize role name to match quiz system
        role_normalized = role
        for quiz_role in ['teacher', 'software engineer', 'data analyst', 'ux designer', 'product manager', 'marketing', 'graphic designer']:
            if quiz_role.split()[0] in role or any(word in role for word in quiz_role.split()):
                role_normalized = quiz_role
                break
        
        # Generate profession-specific activity tasks
        tasks = []
        if 'teacher' in role:
            tasks = [
                {'title': 'Read curriculum guides', 'detail': 'Study current curriculum standards for your grade'},
                {'title': 'Prepare 3 lesson plans', 'detail': 'Create scaffolded lesson plans with assessments'},
                {'title': 'Join teacher forum', 'detail': 'Participate in a local teacher community forum'}
            ]
        elif 'data' in role or 'analyst' in role:
            tasks = [
                {'title': 'Learn SQL', 'detail': 'Complete SQL exercises on filtering and aggregation'},
                {'title': 'Project: Data analysis', 'detail': 'Analyze a dataset and publish findings'},
                {'title': 'Build portfolio', 'detail': 'Create a GitHub repo with notebooks and visuals'}
            ]
        elif 'ux' in role or 'designer' in role or 'graphic' in role:
            tasks = [
                {'title': 'User research', 'detail': 'Run a small user interview study'},
                {'title': 'Design case study', 'detail': 'Document a design process and outcomes'},
                {'title': 'Prototype', 'detail': 'Build a clickable prototype in Figma'}
            ]
        elif 'software' in role or 'engineer' in role or 'developer' in role or 'programmer' in role:
            tasks = [
                {'title': 'Build a project', 'detail': 'Create a full-stack application'},
                {'title': 'Contribute to open source', 'detail': 'Submit PRs to an open source project'},
                {'title': 'System design', 'detail': 'Practice architecture and scalability design'}
            ]
        elif 'product' in role or 'manager' in role or 'pm' in role:
            tasks = [
                {'title': 'Define product strategy', 'detail': 'Create a product strategy document'},
                {'title': 'Build roadmap', 'detail': 'Develop a prioritized product roadmap'},
                {'title': 'User research', 'detail': 'Conduct interviews and user surveys'}
            ]
        elif 'market' in role or 'seo' in role:
            tasks = [
                {'title': 'Content strategy', 'detail': 'Plan a content marketing calendar'},
                {'title': 'Campaign analysis', 'detail': 'Analyze metrics and ROI of campaigns'},
                {'title': 'Build audience', 'detail': 'Grow social media presence or email list'}
            ]
        elif 'doctor' in role or 'nurse' in role or 'medical' in role or 'healthcare' in role:
            tasks = [
                {'title': 'Study medical protocols', 'detail': 'Learn current treatment guidelines'},
                {'title': 'Case study analysis', 'detail': 'Analyze and present clinical case studies'},
                {'title': 'Patient care simulation', 'detail': 'Participate in training scenarios'}
            ]
        elif 'account' in role or 'finance' in role or 'cfo' in role or 'analyst' in role:
            tasks = [
                {'title': 'Financial modeling', 'detail': 'Build spreadsheet models for forecasting'},
                {'title': 'Audit preparation', 'detail': 'Learn audit and compliance procedures'},
                {'title': 'Tax planning', 'detail': 'Study tax strategies and regulations'}
            ]
        elif 'engineer' in role and 'civil' in role or 'mechanical' in role or 'electrical' in role:
            tasks = [
                {'title': 'CAD design', 'detail': 'Create engineering drawings and models'},
                {'title': 'Project analysis', 'detail': 'Analyze structural and systems requirements'},
                {'title': 'Technical documentation', 'detail': 'Write specifications and technical reports'}
            ]
        else:
            tasks = [
                {'title': 'Foundational reading', 'detail': f'Read key resources about {role or "target"}'},
                {'title': 'Mini project', 'detail': 'Complete a small project relevant to your goal'},
                {'title': 'Join community', 'detail': 'Find an online community for mentorship'}
            ]

        # Insert activities into a dedicated activities list with levels
        store = self._read_store()
        activities = store.get('activities', [])
        
        # Keep completed activities (persist quiz history) but remove pending activities for this user
        # This preserves completed quizzes while allowing profession changes
        activities = [a for a in activities if not (a.get('userId') == user_id and a.get('status') == 'pending')]
        
        # Create MULTIPLE quizzes per level (5 quizzes per level = basic 1-5, intermediate 1-5, advanced 1-5)
        for level_idx, level in enumerate(['basic', 'intermediate', 'advanced']):
            # 5 quizzes per level
            for quiz_num in range(1, 6):
                task = tasks[level_idx] if level_idx < len(tasks) else tasks[-1] if tasks else {'title': 'Practice', 'detail': 'Continue learning'}
                activity = {
                    'activityId': str(uuid.uuid4()),
                    'userId': user_id,
                    'title': f'{task.get("title")} - Quiz {quiz_num}',
                    'detail': task.get('detail') or task.get('description'),
                    'level': level,
                    'role': role_normalized,
                    'quizVariant': quiz_num,  # Track which variant of the quiz
                    'status': 'pending',
                    'createdAt': datetime.utcnow().isoformat()
                }
                activities.append(activity)

        store['activities'] = activities
        self._write_store(store)
        return [a for a in activities if a.get('userId') == user_id]

    def save_roadmap(self, roadmap):
        if self.table:
            try:
                self.table.put_item(Item=roadmap)
                return True
            except Exception:
                pass

        store = self._read_store()
        rms = store.get('roadmaps', [])
        rms = [r for r in rms if r.get('roadmapId') != roadmap['roadmapId']]
        rms.append(roadmap)
        store['roadmaps'] = rms
        self._write_store(store)
        return True

    def get_roadmap(self, roadmap_id):
        if self.table:
            try:
                resp = self.table.get_item(Key={'roadmapId': roadmap_id})
                return resp.get('Item')
            except Exception:
                pass

        store = self._read_store()
        for r in store.get('roadmaps', []):
            if r.get('roadmapId') == roadmap_id:
                return r
        return None

    # Simple Groq integration
    def generate_with_groq(self, user_id, goal, context):
        # Enhanced AI-powered roadmap generation using Groq
        if self.groq_client:
            try:
                user_profile = context.get('profile', {}) if context else {}
                current_role = user_profile.get('currentRole', '')
                target_role = user_profile.get('targetRole', goal)
                
                prompt = f"""Create a comprehensive, detailed, and practical 6-step learning roadmap for becoming a {goal}.

Context:
- Current Role: {current_role or 'Not specified'}
- Target Role: {goal}
- User Profile: {json.dumps(user_profile) if user_profile else 'Not provided'}

IMPORTANT: This profession may be:
- Common (teacher, doctor, engineer)
- Specialized (CA - Chartered Accountant, IAS - Indian Administrative Service)
- Regional (CA in India, CPA in USA)
- Any profession from any country or industry

Provide a detailed, step-by-step roadmap that is:
1. Specific and actionable (not generic)
2. Tailored to the profession (understand what it actually requires)
3. Realistic and achievable
4. Includes specific skills, tools, certifications, and milestones
5. Suitable for someone transitioning from {current_role or 'their current situation'} to {goal}

Format as JSON:
{{
  "goal": "{goal}",
  "steps": [
    {{
      "title": "Step title (specific and clear)",
      "description": "Detailed description with specific actions, skills to learn, resources, timelines, and milestones. Be comprehensive and practical."
    }}
  ]
}}

Each step should be:
- Specific to the {goal} profession
- Include actionable tasks
- Mention specific skills, tools, or certifications
- Provide realistic timelines or milestones
- Build upon previous steps logically

Make it practical and tailored to actually becoming a {goal}, not generic career advice."""
                
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {'role': 'system', 'content': 'You are an expert career counselor who creates detailed, practical, and accurate learning roadmaps for ANY profession globally. You understand specialized professions, regional variations, and provide specific, actionable guidance.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    model=os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant'),
                    temperature=0.5,  # Lower temperature for more consistent, accurate results
                    max_tokens=2500,
                    response_format={"type": "json_object"}
                )
                
                if chat_completion.choices and len(chat_completion.choices) > 0:
                    response_text = chat_completion.choices[0].message.content.strip()
                    try:
                        result = json.loads(response_text)
                        if result.get('steps') and len(result.get('steps', [])) > 0:
                            return {
                                'generatedAt': datetime.utcnow().isoformat(),
                                'goal': result.get('goal', goal),
                                'steps': result.get('steps', [])
                            }
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                pass
        
        # Role-specific mock templates
        role = (goal or '').lower()
        def teacher_steps():
            return [
                {'title': 'Educational Foundation & Certification', 'description': 'Complete a bachelor\'s degree in education or your subject area. Research and obtain required teaching certification/license for your region. Pass required certification exams (e.g., Praxis, state-specific tests). Consider specialized certifications (ESL, special education) to enhance your profile.'},
                {'title': 'Subject Knowledge & Curriculum Mastery', 'description': 'Deepen expertise in your subject area through advanced coursework or self-study. Study current curriculum standards and learning objectives for your grade level. Familiarize yourself with educational technology tools and digital resources. Stay updated with pedagogical research and best practices.'},
                {'title': 'Lesson Planning & Instructional Design', 'description': 'Learn to create scaffolded lesson plans with clear objectives, activities, and assessments. Practice designing differentiated instruction for diverse learners. Develop skills in creating engaging, interactive learning experiences. Build a collection of lesson plans and teaching materials.'},
                {'title': 'Classroom Management & Student Engagement', 'description': 'Study effective classroom management strategies and behavior management techniques. Learn active learning methods and student engagement strategies. Practice creating inclusive, supportive learning environments. Gain experience through student teaching, tutoring, or volunteer work.'},
                {'title': 'Assessment, Feedback & Professional Growth', 'description': 'Master formative and summative assessment techniques. Learn to provide constructive, timely feedback to students. Develop skills in data-driven instruction and using assessment results. Join professional teaching organizations and attend workshops or conferences.'},
                {'title': 'Portfolio Development & Job Application', 'description': 'Create a comprehensive teaching portfolio showcasing lesson plans, student work samples, and reflections. Prepare all required certification documents and transcripts. Network with educators and attend job fairs. Apply to school districts, prepare for interviews, and practice demo lessons.'},
            ]

        def software_steps():
            return [
                {'title': 'Programming Foundations & Core Concepts', 'description': 'Master one programming language deeply (Python, JavaScript, or Java recommended). Learn fundamental data structures (arrays, linked lists, stacks, queues, trees, graphs). Study algorithms (sorting, searching, dynamic programming, recursion). Understand time/space complexity (Big O notation) and problem-solving techniques.'},
                {'title': 'Development Tools & Version Control', 'description': 'Become proficient with Git and GitHub for version control. Learn to use IDEs effectively (VS Code, IntelliJ, etc.). Understand command-line tools and terminal usage. Set up development environments and learn package managers (npm, pip, etc.).'},
                {'title': 'Web Development & Full-Stack Projects', 'description': 'Learn frontend (HTML, CSS, JavaScript, React/Vue) and backend (Node.js, Python/Django, or Java/Spring). Understand databases (SQL and NoSQL) and API design (REST, GraphQL). Build 3-5 substantial projects showcasing different skills. Deploy projects to platforms like Heroku, AWS, or Vercel.'},
                {'title': 'Software Engineering Practices', 'description': 'Learn software testing (unit, integration, end-to-end tests). Understand CI/CD pipelines and DevOps basics. Study design patterns and software architecture principles. Practice code reviews, documentation, and clean code practices. Contribute to open-source projects.'},
                {'title': 'System Design & Interview Preparation', 'description': 'Study system design concepts (scalability, load balancing, databases, caching). Practice coding interview problems on platforms like LeetCode, HackerRank. Learn common interview patterns and problem-solving strategies. Practice behavioral interviews using the STAR method. Mock interviews with peers or mentors.'},
                {'title': 'Portfolio, Resume & Job Search', 'description': 'Create a professional GitHub profile with well-documented projects. Build a portfolio website showcasing your work. Optimize your LinkedIn profile and resume with relevant keywords. Network with developers, attend meetups, and engage in tech communities. Apply to entry-level positions and internships, prepare for technical interviews.'},
            ]

        def data_steps():
            return [
                {'title': 'Foundational Skills: SQL & Statistics', 'description': 'Master SQL for querying databases (JOINs, subqueries, window functions, aggregations). Learn statistical concepts (descriptive statistics, probability, hypothesis testing, distributions). Understand data types, data quality issues, and data cleaning techniques. Practice with real datasets on platforms like Kaggle or public data sources.'},
                {'title': 'Programming & Data Manipulation Tools', 'description': 'Learn Python for data analysis (pandas for data manipulation, NumPy for numerical computing). Master Excel/Google Sheets for basic analytics and pivot tables. Learn data visualization libraries (Matplotlib, Seaborn, Plotly). Understand data wrangling and ETL (Extract, Transform, Load) processes.'},
                {'title': 'Data Visualization & Business Intelligence', 'description': 'Learn visualization tools like Tableau, Power BI, or Looker. Master creating dashboards and reports that tell compelling data stories. Understand design principles for effective data visualization. Practice creating visualizations that drive business decisions.'},
                {'title': 'Data Analysis Projects & Case Studies', 'description': 'Complete end-to-end data analysis projects (data cleaning, exploration, analysis, visualization). Work on projects across different domains (business, healthcare, finance, etc.). Document your analysis process and findings clearly. Build a portfolio of 3-5 comprehensive analysis projects.'},
                {'title': 'Advanced Analytics & Machine Learning (Optional)', 'description': 'Learn machine learning fundamentals (supervised/unsupervised learning, model evaluation). Understand when to use different ML algorithms. Practice building predictive models with scikit-learn. Learn about model interpretation and business impact. Note: Focus on practical application over deep theory for analyst roles.'},
                {'title': 'Portfolio Development & Interview Preparation', 'description': 'Create a GitHub portfolio with Jupyter notebooks showcasing your analysis. Write case studies explaining your methodology and insights. Prepare for data analyst interviews (SQL tests, case studies, behavioral questions). Network with data professionals, join data science communities. Apply to positions and highlight your analytical thinking and communication skills.'},
            ]

        def ux_steps():
            return [
                {'title': 'UX Design Foundations & Design Thinking', 'description': 'Learn fundamental UX principles (usability, accessibility, user-centered design). Study design thinking methodology (empathize, define, ideate, prototype, test). Understand user research methods (interviews, surveys, personas, user journeys). Learn information architecture and content strategy basics.'},
                {'title': 'Design Tools & Prototyping Skills', 'description': 'Master design tools like Figma, Sketch, or Adobe XD. Learn to create wireframes, mockups, and high-fidelity prototypes. Understand design systems and component libraries. Practice creating interactive prototypes for user testing. Learn basic UI design principles (typography, color, spacing, hierarchy).'},
                {'title': 'User Research & Usability Testing', 'description': 'Learn to conduct user interviews and usability testing sessions. Understand how to analyze research findings and synthesize insights. Practice creating user personas, journey maps, and empathy maps. Learn to document research findings and present them effectively. Gain experience through volunteer projects or internships.'},
                {'title': 'Portfolio Development: Case Studies', 'description': 'Complete 3-5 comprehensive UX design projects from research to final design. Document your process: problem statement, research, ideation, design iterations, testing, and outcomes. Create detailed case studies showing your thinking and problem-solving approach. Showcase both process and final designs in your portfolio.'},
                {'title': 'Accessibility, Metrics & UX Impact', 'description': 'Learn accessibility standards (WCAG guidelines) and inclusive design principles. Understand how to measure UX success (conversion rates, task completion, user satisfaction). Learn A/B testing and data-driven design decisions. Study how UX impacts business metrics and ROI.'},
                {'title': 'Interview Preparation & Career Launch', 'description': 'Prepare your portfolio website showcasing your best case studies. Practice portfolio walkthroughs and design challenge presentations. Network with UX designers on LinkedIn, attend design meetups, and join design communities. Apply to UX positions (junior roles, internships, or apprenticeships). Prepare for behavioral and portfolio review interviews.'},
            ]

        # choose template
        if 'teacher' in role or 'teaching' in role or 'educator' in role:
            steps = teacher_steps()
        elif 'data' in role or 'analyst' in role or 'machine learning' in role:
            steps = data_steps()
        elif 'ux' in role or 'designer' in role or 'ui' in role:
            steps = ux_steps()
        elif 'software' in role or 'engineer' in role or 'developer' in role:
            steps = software_steps()
        else:
            # Enhanced generic fallback with detailed steps
            steps = [
                {'title': 'Research & Education Foundation', 'description': f'Research the {goal} profession: required qualifications, certifications, and educational background. Identify core knowledge areas and skills needed. Enroll in relevant courses, certifications, or degree programs. Study industry standards, best practices, and current trends in the field.'},
                {'title': 'Skill Development & Practical Experience', 'description': f'Develop both technical and soft skills relevant to {goal}. Gain hands-on experience through projects, internships, volunteer work, or entry-level positions. Practice using industry-standard tools and technologies. Build a portfolio of work demonstrating your capabilities.'},
                {'title': 'Professional Tools & Industry Knowledge', 'description': f'Master the tools, software, and technologies commonly used in {goal} roles. Understand industry workflows, processes, and methodologies. Stay updated with industry news, trends, and emerging technologies. Join professional associations or communities related to your field.'},
                {'title': 'Networking & Professional Development', 'description': f'Build a professional network by connecting with professionals in {goal} roles. Attend industry events, conferences, webinars, or meetups. Seek mentorship from experienced professionals. Engage in online communities, forums, and social media groups related to your field.'},
                {'title': 'Portfolio & Interview Preparation', 'description': f'Create a comprehensive portfolio showcasing your skills, projects, and achievements relevant to {goal}. Prepare for role-specific interviews by researching common questions and requirements. Practice articulating your experience and how it relates to the position. Develop your personal brand and professional presence.'},
                {'title': 'Job Search & Career Launch', 'description': f'Optimize your resume and LinkedIn profile with keywords relevant to {goal} positions. Apply strategically to entry-level positions, internships, or apprenticeships. Prepare for interviews and assessment processes. Follow up on applications and maintain persistence in your job search. Consider freelance or contract work to gain experience.'},
            ]

        return {'generatedAt': datetime.utcnow().isoformat(), 'goal': goal, 'steps': steps}

    def generate_roadmap(self, user_id, goal, context=None):
        roadmap_id = str(uuid.uuid4())
        generated = self.generate_with_groq(user_id, goal, context or {})
        roadmap = {
            'roadmapId': roadmap_id,
            'userId': user_id,
            'goal': goal,
            'steps': generated.get('steps') if isinstance(generated, dict) else [],
            'generatedAt': generated.get('generatedAt', datetime.utcnow().isoformat()),
        }
        self.save_roadmap(roadmap)
        # Optionally publish a notification
        try:
            if self.sns and self.sns_topic:
                self.sns.publish(TopicArn=self.sns_topic, Message=f'Roadmap {roadmap_id} generated for user {user_id}')
        except Exception:
            pass
        return roadmap

    def chat_with_ai(self, user_id, message):
        # Very small wrapper: call the generator with a short prompt to simulate chat
        ctx = {'userId': user_id}
        reply = self.generate_with_groq(user_id, f'Answer: {message}', ctx)
        if isinstance(reply, dict):
            # attempt to create a short textual reply
            steps = reply.get('steps') or []
            if steps:
                return steps[0].get('description')
            return json.dumps(reply)
        return str(reply)

    # New: flexible chat provider wrapper
    def chat_with_provider(self, user_id, message):
        # Prefer Groq if API key present, then Hugging Face, then OpenAI, then fallback mock
        if self.groq_client:
            try:
                model = os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant')
                system_prompt = os.environ.get('GROQ_SYSTEM_PROMPT', 'You are a helpful, concise virtual career counselor. Provide actionable, role-specific advice and learning steps. Keep answers factual and friendly.')
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': message}
                    ],
                    model=model,
                    temperature=0.7,
                    max_tokens=800
                )
                if chat_completion.choices and len(chat_completion.choices) > 0:
                    return chat_completion.choices[0].message.content.strip()
            except Exception:
                pass
        
        hf_key = os.environ.get('HF_API_KEY')
        if hf_key:
            try:
                headers = { 'Authorization': f'Bearer {hf_key}' }
                model = os.environ.get('HF_MODEL', 'google/flan-t5-small')
                # For HF Inference API, many models accept {'inputs': message}
                resp = requests.post(f'https://api-inference.huggingface.co/models/{model}', headers=headers, json={'inputs': message}, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    # Hugging Face can return list of dicts or dict with generated_text
                    if isinstance(data, list) and len(data) and isinstance(data[0], dict):
                        # e.g. [{'generated_text': '...'}]
                        if 'generated_text' in data[0]:
                            return data[0]['generated_text']
                        # some models return 'summary_text' or plain string
                        for k in ('generated_text','summary_text','text'):
                            if k in data[0]:
                                return data[0][k]
                        return str(data[0])
                    if isinstance(data, dict):
                        if 'generated_text' in data:
                            return data['generated_text']
                        # some HF endpoints return {'error': ...}
                        if 'error' in data:
                            # let fallback try OpenAI
                            pass
                        else:
                            # try to stringify useful keys
                            for k in ('generated_text','summary_text','text'):
                                if k in data:
                                    return data[k]
                            return str(data)
            except Exception:
                pass

        # OpenAI fallback
        openai_key = os.environ.get('OPENAI_API_KEY')
        if openai_key:
            try:
                model = os.environ.get('OPENAI_MODEL', 'gpt-3.5-turbo')
                headers = {'Authorization': f'Bearer {openai_key}', 'Content-Type': 'application/json'}
                system_prompt = os.environ.get('OPENAI_SYSTEM_PROMPT', 'You are a helpful, concise virtual career counselor. Provide actionable, role-specific advice and learning steps. Keep answers factual and friendly.')
                payload = {
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': message}
                    ],
                    'temperature': float(os.environ.get('OPENAI_TEMPERATURE', '0.4')),
                    'max_tokens': int(os.environ.get('OPENAI_MAX_TOKENS', '600'))
                }
                resp = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=payload, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    if 'choices' in data and len(data['choices'])>0 and 'message' in data['choices'][0]:
                        return data['choices'][0]['message'].get('content','').strip()
            except Exception:
                pass

        # Enhanced fallback: intelligent career counseling responses
        msg_lower = message.lower()
        
        # Get user context if available
        user = self.get_user(user_id)
        user_role = None
        if user and user.get('profile'):
            user_role = (user['profile'].get('targetRole') or user['profile'].get('role') or '').lower()
        
        # Resume/CV related
        if any(word in msg_lower for word in ['resume', 'cv', 'curriculum vitae']):
            role_specific = f" For {user_role}, " if user_role else " "
            return f"To improve your resume:{role_specific}highlight relevant projects and achievements, quantify your impact with numbers (e.g., 'increased efficiency by 30%'), match keywords from job descriptions, use action verbs, and keep it concise (1-2 pages). Include a skills section tailored to your target role."
        
        # Interview related
        if any(word in msg_lower for word in ['interview', 'interviewing', 'interview prep']):
            role_specific = f" For {user_role} roles, " if user_role else " "
            return f"Interview preparation tips:{role_specific}research the company and role thoroughly, practice common questions using the STAR method (Situation, Task, Action, Result), prepare questions to ask them, dress professionally, and practice technical skills if applicable. Be ready to discuss your experience and how it relates to the position."
        
        # Career path/roadmap related
        if any(word in msg_lower for word in ['roadmap', 'path', 'become', 'how to', 'career path', 'steps']):
            if user_role:
                return f"To become a {user_role}, I recommend: 1) Build foundational knowledge through courses and certifications, 2) Gain hands-on experience through projects or internships, 3) Network with professionals in the field, 4) Create a portfolio showcasing your work, 5) Apply for entry-level positions and continuously learn. Would you like me to generate a detailed roadmap for {user_role}?"
            return "I can help you create a personalized career roadmap! Please specify your target profession (e.g., 'I want to become a software engineer' or 'How do I become a data analyst?'), and I'll generate a step-by-step plan tailored to your goals."
        
        # Skills/learning related
        if any(word in msg_lower for word in ['skill', 'learn', 'study', 'course', 'training']):
            if user_role:
                return f"For {user_role}, key skills to develop include: technical proficiency in industry-standard tools, problem-solving abilities, communication skills, and continuous learning mindset. I can suggest specific learning resources and activities. Would you like to see recommended activities for {user_role}?"
            return "Developing relevant skills is crucial for career growth. Focus on both technical skills (tools, technologies) and soft skills (communication, teamwork). What profession are you interested in? I can provide specific skill recommendations."
        
        # Salary/compensation related
        if any(word in msg_lower for word in ['salary', 'pay', 'compensation', 'earn', 'income']):
            return "Salary varies by location, experience, and company. Research platforms like Glassdoor, LinkedIn Salary, and PayScale for current market rates. Focus on building skills and experience first - compensation follows expertise. Would you like advice on negotiating offers?"
        
        # Job search related
        if any(word in msg_lower for word in ['job', 'apply', 'application', 'hiring', 'position']):
            return "Job search strategy: 1) Optimize your LinkedIn profile, 2) Tailor your resume for each application, 3) Use multiple job boards (LinkedIn, Indeed, company websites), 4) Network actively, 5) Prepare for interviews, 6) Follow up after applications. Consistency and persistence are key!"
        
        # General career advice
        if any(word in msg_lower for word in ['career', 'profession', 'future', 'guidance', 'advice']):
            return "I'm here to help with your career journey! I can assist with: career planning, skill development, resume building, interview preparation, learning roadmaps, and professional growth strategies. What specific area would you like help with? You can also ask me to generate a roadmap for your target profession."
        
        # Role-specific questions
        if user_role:
            if 'teacher' in user_role or 'educator' in user_role:
                if any(word in msg_lower for word in ['certification', 'certificate', 'qualification']):
                    return "For teaching, you typically need: a bachelor's degree in education or your subject area, teaching certification/license (varies by region), student teaching experience, and passing certification exams. Research requirements in your specific location."
            elif 'software' in user_role or 'engineer' in user_role or 'developer' in user_role:
                if any(word in msg_lower for word in ['language', 'programming', 'code']):
                    return "For software engineering, start with one language deeply (Python, JavaScript, or Java are great choices), then learn data structures, algorithms, version control (Git), and build projects. Focus on problem-solving and clean code practices."
            elif 'data' in user_role or 'analyst' in user_role:
                if any(word in msg_lower for word in ['sql', 'python', 'analysis', 'data']):
                    return "For data analysis, master SQL for data querying, Python (pandas, NumPy) or R for analysis, Excel for basic analytics, visualization tools (Tableau, Power BI), and statistical concepts. Practice with real datasets and build a portfolio."
        
        # Default helpful response
        return f"I'm your virtual career counselor! I can help with career planning, skill development, resume tips, interview prep, and creating personalized learning roadmaps. Since you're interested in {user_role} if user_role else 'Try asking me specific questions like: 'How do I become a [profession]?', 'What skills do I need?', 'Help me with my resume', or 'Prepare me for interviews'. I can also generate a detailed roadmap for your career goals!"

    # Career Path Exploration - Comprehensive career information
    def explore_career_path(self, career_name, user_id=None):
        """Get comprehensive career path information including skills, courses, certifications, exams, and job roles"""
        if self.groq_client:
            try:
                prompt = f"""You are an expert career counselor. Provide comprehensive, detailed, and accurate career information for the profession: "{career_name}". 

IMPORTANT: This profession may be:
- A common profession (like teacher, doctor, engineer)
- A specialized profession (like CA - Chartered Accountant, IAS - Indian Administrative Service)
- A regional profession (like CA in India, CPA in USA)
- Any profession from any country or industry

Research and provide accurate information regardless of how common or specialized the profession is. If the profession is an acronym (like CA, CPA, IAS), explain what it stands for and provide full details.

Format your response as JSON with the following structure:
{{
  "career": "{career_name}",
  "overview": "Comprehensive overview explaining what this profession is, what professionals do, and the field they work in. If it's an acronym, explain the full name and meaning.",
  "required_skills": ["skill1", "skill2", "skill3", "skill4", "skill5", "skill6", "skill7", "skill8"],
  "recommended_courses": [
    {{"name": "Course Name", "description": "Detailed course description", "platform": "Platform name (Coursera, Udemy, edX, etc.)", "duration": "Duration", "level": "Beginner/Intermediate/Advanced", "rating": "Rating if known"}}
  ],
  "certifications": [
    {{"name": "Certification Name", "issuer": "Issuing organization", "description": "What it covers and why it's important", "validity": "Validity period"}}
  ],
  "exams": [
    {{"name": "Exam Name", "description": "Exam description and purpose", "format": "Format (online/in-person)", "preparation_time": "Typical prep time"}}
  ],
  "job_roles": [
    {{"title": "Job Title", "description": "Detailed role description", "experience_level": "Entry/Mid/Senior"}}
  ],
  "salary_range": {{"entry": "Entry level range with currency", "mid": "Mid level range with currency", "senior": "Senior level range with currency"}},
  "growth_outlook": "Career growth prospects, demand, and future outlook"
}}

Be specific, practical, and accurate. Include:
- 6-10 specific required skills
- 6-10 recommended courses from real platforms (Coursera, Udemy, edX, Khan Academy, etc.)
- 3-5 relevant certifications
- 2-4 important exams or qualifications
- 4-6 different job roles at various levels
- Realistic salary ranges with currency
- Honest growth outlook based on current market trends

If the profession is specialized or regional, provide information specific to that context."""
                
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {'role': 'system', 'content': 'You are a world-class career counselor with expertise in ALL professions globally. You provide detailed, accurate, and practical career information for ANY profession, including specialized, regional, or less common ones. Always explain acronyms and provide comprehensive details regardless of how common the profession is.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    model=os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant'),
                    temperature=0.4,
                    max_tokens=3000,
                    response_format={"type": "json_object"}
                )
                
                if chat_completion.choices and len(chat_completion.choices) > 0:
                    response_text = chat_completion.choices[0].message.content.strip()
                    try:
                        result = json.loads(response_text)
                        # Record activity
                        if user_id:
                            self.record_activity(user_id, 'explore_career', {'career': career_name})
                        return result
                    except json.JSONDecodeError:
                        # If JSON parsing fails, try to extract structured data
                        pass
            except Exception as e:
                pass
        
        # Fallback: Return structured data based on career name
        return self._get_career_path_fallback(career_name, user_id)

    def _get_career_path_fallback(self, career_name, user_id):
        """Fallback career path data when AI is not available"""
        career_lower = career_name.lower()
        
        # Software Engineer/Developer
        if any(word in career_lower for word in ['software', 'developer', 'programmer', 'engineer']):
            return {
                "career": career_name,
                "overview": "Software engineers design, develop, and maintain software applications and systems.",
                "required_skills": ["Programming (Python/Java/JavaScript)", "Data Structures & Algorithms", "Version Control (Git)", "Database Management", "Software Testing", "System Design", "Problem Solving", "Agile Methodologies"],
                "recommended_courses": [
                    {"name": "Complete Python Bootcamp", "description": "Master Python programming from basics to advanced", "platform": "Udemy", "duration": "40 hours"},
                    {"name": "Data Structures and Algorithms", "description": "Learn fundamental algorithms and data structures", "platform": "Coursera", "duration": "6 weeks"},
                    {"name": "Full Stack Web Development", "description": "Build complete web applications", "platform": "freeCodeCamp", "duration": "300 hours"},
                    {"name": "System Design Interview", "description": "Learn to design scalable systems", "platform": "Educative", "duration": "20 hours"}
                ],
                "certifications": [
                    {"name": "AWS Certified Developer", "issuer": "Amazon Web Services", "description": "Cloud development and deployment", "validity": "3 years"},
                    {"name": "Google Cloud Professional Developer", "issuer": "Google Cloud", "description": "Cloud-native application development", "validity": "3 years"}
                ],
                "exams": [
                    {"name": "Technical Coding Interview", "description": "Algorithm and problem-solving assessment", "format": "Online/In-person", "preparation_time": "2-3 months"}
                ],
                "job_roles": [
                    {"title": "Junior Software Developer", "description": "Entry-level development role", "experience_level": "Entry"},
                    {"title": "Software Engineer", "description": "Mid-level development and design", "experience_level": "Mid"},
                    {"title": "Senior Software Engineer", "description": "Lead development and architecture", "experience_level": "Senior"}
                ],
                "salary_range": {"entry": "$60,000 - $90,000", "mid": "$90,000 - $130,000", "senior": "$130,000 - $180,000+"},
                "growth_outlook": "Excellent - High demand with 22% projected growth"
            }
        
        # Data Analyst
        elif any(word in career_lower for word in ['data analyst', 'data analysis']):
            return {
                "career": career_name,
                "overview": "Data analysts interpret complex data to help organizations make informed decisions.",
                "required_skills": ["SQL", "Python/R", "Excel", "Data Visualization (Tableau/Power BI)", "Statistics", "Data Cleaning", "Business Acumen", "Communication"],
                "recommended_courses": [
                    {"name": "SQL for Data Analysis", "description": "Master SQL queries and data manipulation", "platform": "DataCamp", "duration": "20 hours"},
                    {"name": "Python for Data Science", "description": "Learn pandas, NumPy, and data analysis", "platform": "Coursera", "duration": "8 weeks"},
                    {"name": "Tableau Desktop Specialist", "description": "Create interactive dashboards", "platform": "Udemy", "duration": "15 hours"},
                    {"name": "Statistics for Data Science", "description": "Statistical analysis and hypothesis testing", "platform": "edX", "duration": "6 weeks"}
                ],
                "certifications": [
                    {"name": "Google Data Analytics Certificate", "issuer": "Google", "description": "Comprehensive data analytics skills", "validity": "Lifetime"},
                    {"name": "Microsoft Certified: Data Analyst Associate", "issuer": "Microsoft", "description": "Power BI and data analysis", "validity": "2 years"}
                ],
                "exams": [
                    {"name": "Data Analysis Case Study", "description": "Practical data analysis project", "format": "Online", "preparation_time": "1-2 months"}
                ],
                "job_roles": [
                    {"title": "Junior Data Analyst", "description": "Entry-level data analysis", "experience_level": "Entry"},
                    {"title": "Data Analyst", "description": "Mid-level analysis and reporting", "experience_level": "Mid"},
                    {"title": "Senior Data Analyst", "description": "Advanced analysis and strategy", "experience_level": "Senior"}
                ],
                "salary_range": {"entry": "$55,000 - $75,000", "mid": "$75,000 - $100,000", "senior": "$100,000 - $130,000+"},
                "growth_outlook": "Excellent - 25% projected growth, high demand"
            }
        
        # Teacher/Educator
        elif any(word in career_lower for word in ['teacher', 'educator', 'teaching']):
            return {
                "career": career_name,
                "overview": "Teachers educate and inspire students, creating engaging learning environments.",
                "required_skills": ["Subject Matter Expertise", "Lesson Planning", "Classroom Management", "Communication", "Patience", "Adaptability", "Assessment Design", "Technology Integration"],
                "recommended_courses": [
                    {"name": "Teaching Methods and Strategies", "description": "Effective teaching techniques", "platform": "Coursera", "duration": "6 weeks"},
                    {"name": "Classroom Management", "description": "Managing student behavior and engagement", "platform": "edX", "duration": "4 weeks"},
                    {"name": "Educational Technology", "description": "Integrating technology in teaching", "platform": "Udemy", "duration": "10 hours"},
                    {"name": "Special Education Basics", "description": "Supporting diverse learners", "platform": "FutureLearn", "duration": "3 weeks"}
                ],
                "certifications": [
                    {"name": "Teaching License/Certification", "issuer": "State Education Board", "description": "Required teaching credential", "validity": "Renewable"},
                    {"name": "TESOL Certificate", "issuer": "Various", "description": "Teaching English to speakers of other languages", "validity": "Lifetime"}
                ],
                "exams": [
                    {"name": "Praxis Core Academic Skills", "description": "Basic skills assessment", "format": "Computer-based", "preparation_time": "1-2 months"},
                    {"name": "Subject-Specific Praxis", "description": "Content knowledge exam", "format": "Computer-based", "preparation_time": "2-3 months"}
                ],
                "job_roles": [
                    {"title": "Substitute Teacher", "description": "Temporary teaching assignments", "experience_level": "Entry"},
                    {"title": "Classroom Teacher", "description": "Full-time teaching position", "experience_level": "Mid"},
                    {"title": "Department Head/Lead Teacher", "description": "Leadership and curriculum development", "experience_level": "Senior"}
                ],
                "salary_range": {"entry": "$40,000 - $50,000", "mid": "$50,000 - $65,000", "senior": "$65,000 - $85,000+"},
                "growth_outlook": "Stable - Consistent demand, varies by region"
            }
        
        # Generic fallback
        else:
            return {
                "career": career_name,
                "overview": f"{career_name} is a professional career path that requires specific skills and qualifications.",
                "required_skills": ["Industry-specific knowledge", "Communication skills", "Problem-solving", "Technical proficiency", "Continuous learning"],
                "recommended_courses": [
                    {"name": f"Introduction to {career_name}", "description": "Foundational course", "platform": "Various", "duration": "Varies"},
                    {"name": f"Advanced {career_name} Skills", "description": "Advanced techniques", "platform": "Various", "duration": "Varies"}
                ],
                "certifications": [
                    {"name": f"{career_name} Certification", "issuer": "Industry Organization", "description": "Professional certification", "validity": "Varies"}
                ],
                "exams": [
                    {"name": f"{career_name} Qualification Exam", "description": "Professional qualification assessment", "format": "Varies", "preparation_time": "2-6 months"}
                ],
                "job_roles": [
                    {"title": f"Junior {career_name}", "description": "Entry-level position", "experience_level": "Entry"},
                    {"title": career_name, "description": "Mid-level professional", "experience_level": "Mid"},
                    {"title": f"Senior {career_name}", "description": "Advanced professional", "experience_level": "Senior"}
                ],
                "salary_range": {"entry": "Varies by location", "mid": "Varies by experience", "senior": "Varies by role"},
                "growth_outlook": "Research current market trends for accurate information"
            }

    # Personalized Course Recommendations
    def get_course_recommendations(self, user_id, preferences=None, career_name=None):
        """Get personalized course recommendations based on user preferences and career"""
        user = self.get_user(user_id)
        user_profile = user.get('profile', {}) if user else {}
        target_role = (user_profile.get('targetRole') or user_profile.get('role') or career_name or '').lower()
        
        if self.groq_client:
            try:
                preferences_text = json.dumps(preferences) if preferences else "None specified"
                career_context = f" for the career/profession: {career_name}" if career_name else ""
                prompt = f"""Based on the following user profile and preferences, recommend 10-15 comprehensive, personalized courses{career_context}:

User Profile:
- Target Role/Career: {career_name or target_role or 'Not specified'}
- Current Role: {user_profile.get('currentRole', 'Not specified')}
- Preferences: {preferences_text}

Provide course recommendations in JSON format:
{{
  "recommendations": [
    {{
      "course_name": "Course Name",
      "description": "Detailed course description explaining what you'll learn",
      "platform": "Platform name (Coursera, Udemy, edX, Khan Academy, LinkedIn Learning, etc.)",
      "duration": "Course duration (e.g., '6 weeks', '40 hours', 'Self-paced')",
      "level": "Beginner/Intermediate/Advanced",
      "rating": "Rating if available (e.g., '4.7/5', '4.8 stars')",
      "price": "Price or Free (e.g., '$49.99', 'Free', 'Free with certificate $49')",
      "why_recommended": "Why this course fits the user and their career goals",
      "skills_covered": ["skill1", "skill2", "skill3"],
      "url": "Course URL if available (optional)"
    }}
  ],
  "summary": "Brief summary of recommendations and how they align with career goals"
}}

IMPORTANT:
- Recommend 10-15 courses covering different aspects of the career
- Include courses from multiple platforms (Coursera, Udemy, edX, Khan Academy, LinkedIn Learning, etc.)
- Mix of beginner, intermediate, and advanced courses
- Include both free and paid options
- Be specific about what each course teaches
- Make recommendations practical and aligned with the user's career goals
- If career_name is provided, focus heavily on that specific profession"""
                
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {'role': 'system', 'content': 'You are an expert career counselor specializing in educational recommendations. You recommend comprehensive course lists from real platforms like Coursera, Udemy, edX, Khan Academy, and LinkedIn Learning. Provide practical, high-quality course suggestions that align with career goals.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    model=os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant'),
                    temperature=0.5,
                    max_tokens=3000,
                    response_format={"type": "json_object"}
                )
                
                if chat_completion.choices and len(chat_completion.choices) > 0:
                    response_text = chat_completion.choices[0].message.content.strip()
                    try:
                        result = json.loads(response_text)
                        self.record_activity(user_id, 'course_recommendations', {'target_role': target_role})
                        return result
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass
        
        # Fallback recommendations
        return self._get_course_recommendations_fallback(target_role, user_id)

    def _get_course_recommendations_fallback(self, target_role, user_id):
        """Fallback course recommendations"""
        if 'software' in target_role or 'engineer' in target_role or 'developer' in target_role:
            return {
                "recommendations": [
                    {"course_name": "The Complete Python Bootcamp", "description": "Master Python from zero to hero", "platform": "Udemy", "duration": "22 hours", "level": "Beginner", "rating": "4.6/5", "price": "$94.99", "why_recommended": "Essential for software development", "skills_covered": ["Python", "Programming", "OOP"]},
                    {"course_name": "JavaScript: The Complete Guide", "description": "Modern JavaScript development", "platform": "Udemy", "duration": "52 hours", "level": "Intermediate", "rating": "4.7/5", "price": "$94.99", "why_recommended": "Core web development skill", "skills_covered": ["JavaScript", "ES6+", "DOM"]},
                    {"course_name": "Data Structures and Algorithms", "description": "Master algorithms and problem-solving", "platform": "Coursera", "duration": "6 weeks", "level": "Intermediate", "rating": "4.8/5", "price": "Free (audit)", "why_recommended": "Critical for technical interviews", "skills_covered": ["Algorithms", "Data Structures", "Problem Solving"]}
                ],
                "summary": "Recommended courses for software development career"
            }
        elif 'data' in target_role or 'analyst' in target_role:
            return {
                "recommendations": [
                    {"course_name": "SQL for Data Science", "description": "Master SQL for data analysis", "platform": "Coursera", "duration": "4 weeks", "level": "Beginner", "rating": "4.7/5", "price": "Free (audit)", "why_recommended": "Essential for data analysis", "skills_covered": ["SQL", "Database", "Queries"]},
                    {"course_name": "Python for Data Analysis", "description": "Learn pandas and data manipulation", "platform": "DataCamp", "duration": "20 hours", "level": "Intermediate", "rating": "4.6/5", "price": "$25/month", "why_recommended": "Industry-standard tool", "skills_covered": ["Python", "Pandas", "Data Analysis"]}
                ],
                "summary": "Recommended courses for data analysis career"
            }
        else:
            return {
                "recommendations": [
                    {"course_name": "Introduction to Career Development", "description": "Explore career paths and skills", "platform": "Coursera", "duration": "4 weeks", "level": "Beginner", "rating": "4.5/5", "price": "Free (audit)", "why_recommended": "General career guidance", "skills_covered": ["Career Planning", "Skills Assessment"]}
                ],
                "summary": "General course recommendations"
            }

    # Job Market Insights
    def get_job_market_insights(self, career_name, region=None):
        """Get job market insights including trends, skills, salary, and availability"""
        if self.groq_client:
            try:
                region_text = f" in {region}" if region else " globally"
                prompt = f"""Provide comprehensive job market insights for "{career_name}"{region_text}. Format as JSON:

{{
  "career": "{career_name}",
  "region": "{region or 'Global'}",
  "market_trends": {{
    "demand_level": "High/Medium/Low",
    "growth_rate": "Percentage or description",
    "trend_description": "Current market trends"
  }},
  "in_demand_skills": ["skill1", "skill2", "skill3"],
  "salary_insights": {{
    "entry_level": "Salary range",
    "mid_level": "Salary range",
    "senior_level": "Salary range",
    "factors": ["Factor affecting salary"]
  }},
  "job_availability": {{
    "entry_level": "Availability description",
    "mid_level": "Availability description",
    "senior_level": "Availability description"
  }},
  "top_regions": [
    {{"region": "Region name", "demand": "High/Medium/Low", "avg_salary": "Salary range"}}
  ],
  "future_outlook": "Future prospects and predictions"
}}

Be specific and data-driven where possible."""
                
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {'role': 'system', 'content': 'You are a job market analyst. Provide accurate, data-driven insights about career markets.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    model=os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant'),
                    temperature=0.3,
                    max_tokens=2000,
                    response_format={"type": "json_object"}
                )
                
                if chat_completion.choices and len(chat_completion.choices) > 0:
                    response_text = chat_completion.choices[0].message.content.strip()
                    try:
                        return json.loads(response_text)
                    except json.JSONDecodeError:
                        pass
            except Exception:
                pass
        
        # Fallback insights
        return self._get_job_market_insights_fallback(career_name, region)

    def _get_job_market_insights_fallback(self, career_name, region):
        """Fallback job market insights"""
        career_lower = career_name.lower()
        
        if any(word in career_lower for word in ['software', 'developer', 'engineer']):
            return {
                "career": career_name,
                "region": region or "Global",
                "market_trends": {
                    "demand_level": "Very High",
                    "growth_rate": "22% (2022-2032)",
                    "trend_description": "Strong demand for software developers across all industries, especially in cloud, AI/ML, and cybersecurity"
                },
                "in_demand_skills": ["Cloud Computing (AWS/Azure)", "Machine Learning", "DevOps", "Full-Stack Development", "Cybersecurity", "Mobile Development"],
                "salary_insights": {
                    "entry_level": "$60,000 - $90,000",
                    "mid_level": "$90,000 - $130,000",
                    "senior_level": "$130,000 - $200,000+",
                    "factors": ["Location", "Company size", "Specialization", "Experience"]
                },
                "job_availability": {
                    "entry_level": "Moderate - Competitive but growing",
                    "mid_level": "High - Strong demand",
                    "senior_level": "Very High - High demand, premium salaries"
                },
                "top_regions": [
                    {"region": "Silicon Valley, CA", "demand": "Very High", "avg_salary": "$120,000 - $180,000"},
                    {"region": "Seattle, WA", "demand": "High", "avg_salary": "$100,000 - $150,000"},
                    {"region": "New York, NY", "demand": "High", "avg_salary": "$95,000 - $140,000"}
                ],
                "future_outlook": "Excellent - Continued growth expected, especially in AI, cloud, and security specializations"
            }
        elif any(word in career_lower for word in ['data analyst', 'data analysis']):
            return {
                "career": career_name,
                "region": region or "Global",
                "market_trends": {
                    "demand_level": "High",
                    "growth_rate": "25% (2022-2032)",
                    "trend_description": "Rapidly growing field as organizations increasingly rely on data-driven decisions"
                },
                "in_demand_skills": ["SQL", "Python", "Tableau/Power BI", "Machine Learning Basics", "Statistics", "Business Analytics"],
                "salary_insights": {
                    "entry_level": "$55,000 - $75,000",
                    "mid_level": "$75,000 - $100,000",
                    "senior_level": "$100,000 - $140,000+",
                    "factors": ["Industry", "Location", "Technical skills depth", "Business acumen"]
                },
                "job_availability": {
                    "entry_level": "Good - Growing opportunities",
                    "mid_level": "High - Strong demand",
                    "senior_level": "High - Premium positions available"
                },
                "top_regions": [
                    {"region": "San Francisco, CA", "demand": "Very High", "avg_salary": "$85,000 - $130,000"},
                    {"region": "New York, NY", "demand": "High", "avg_salary": "$75,000 - $115,000"},
                    {"region": "Chicago, IL", "demand": "High", "avg_salary": "$70,000 - $105,000"}
                ],
                "future_outlook": "Excellent - Data-driven decision making is becoming essential across all industries"
            }
        else:
            return {
                "career": career_name,
                "region": region or "Global",
                "market_trends": {
                    "demand_level": "Varies",
                    "growth_rate": "Research current trends",
                    "trend_description": "Market conditions vary by industry and location"
                },
                "in_demand_skills": ["Industry-specific skills", "Communication", "Problem-solving"],
                "salary_insights": {
                    "entry_level": "Varies by location and industry",
                    "mid_level": "Varies by experience",
                    "senior_level": "Varies by role and company",
                    "factors": ["Location", "Industry", "Experience", "Education"]
                },
                "job_availability": {
                    "entry_level": "Varies",
                    "mid_level": "Varies",
                    "senior_level": "Varies"
                },
                "top_regions": [
                    {"region": "Research specific regions", "demand": "Varies", "avg_salary": "Varies"}
                ],
                "future_outlook": "Research current market trends for accurate information"
            }

    # Admin Management
    def create_admin(self, email, password, name=None):
        """Create an admin user"""
        admin_id = str(uuid.uuid4())
        admin = {
            'adminId': admin_id,
            'email': email,
            'passwordHash': password,
            'name': name or 'Admin',
            'role': 'admin',
            'createdAt': datetime.utcnow().isoformat()
        }
        store = self._read_store()
        admins = store.get('admins', [])
        admins = [a for a in admins if a.get('email') != email]
        admins.append(admin)
        store['admins'] = admins
        self._write_store(store)
        return admin

    def get_admin_by_email(self, email):
        """Get admin by email"""
        store = self._read_store()
        for a in store.get('admins', []):
            if a.get('email') == email:
                return a
        return None

    def get_admin(self, admin_id):
        """Get admin by ID"""
        store = self._read_store()
        for a in store.get('admins', []):
            if a.get('adminId') == admin_id:
                return a
        return None

    # Job Posting Management
    def create_job_posting(self, admin_id, job_data):
        """Create a new job posting"""
        job_id = str(uuid.uuid4())
        job = {
            'jobId': job_id,
            'adminId': admin_id,
            'title': job_data.get('title', ''),
            'company': job_data.get('company', ''),
            'description': job_data.get('description', ''),
            'requirements': job_data.get('requirements', []),
            'experience_required': job_data.get('experience_required', ''),
            'salary_range': job_data.get('salary_range', ''),
            'location': job_data.get('location', ''),
            'job_type': job_data.get('job_type', 'Full-time'),
            'career_field': job_data.get('career_field', ''),
            'status': 'active',
            'createdAt': datetime.utcnow().isoformat()
        }
        store = self._read_store()
        jobs = store.get('jobs', [])
        jobs.append(job)
        store['jobs'] = jobs
        self._write_store(store)
        return job

    def list_jobs(self, career_field=None, status='active'):
        """List all jobs, optionally filtered by career field"""
        store = self._read_store()
        jobs = store.get('jobs', [])
        if career_field:
            jobs = [j for j in jobs if j.get('career_field', '').lower() == career_field.lower() and j.get('status') == status]
        else:
            jobs = [j for j in jobs if j.get('status') == status]
        return sorted(jobs, key=lambda x: x.get('createdAt', ''), reverse=True)

    def get_job(self, job_id):
        """Get a specific job by ID"""
        store = self._read_store()
        for j in store.get('jobs', []):
            if j.get('jobId') == job_id:
                return j
        return None

    def update_job_status(self, job_id, status):
        """Update job status (active, closed, etc.)"""
        store = self._read_store()
        jobs = store.get('jobs', [])
        for j in jobs:
            if j.get('jobId') == job_id:
                j['status'] = status
                j['updatedAt'] = datetime.utcnow().isoformat()
                store['jobs'] = jobs
                self._write_store(store)
                return True
        return False

    def delete_job(self, job_id):
        """Delete a job posting"""
        store = self._read_store()
        jobs = store.get('jobs', [])
        jobs = [j for j in jobs if j.get('jobId') != job_id]
        store['jobs'] = jobs
        self._write_store(store)
        return True

    # Job Application Management
    def create_job_application(self, user_id, job_id, application_data):
        """Create a job application"""
        application_id = str(uuid.uuid4())
        application = {
            'applicationId': application_id,
            'userId': user_id,
            'jobId': job_id,
            'fullName': application_data.get('fullName', ''),
            'email': application_data.get('email', ''),
            'phone': application_data.get('phone', ''),
            'experience': application_data.get('experience', ''),
            'skills': application_data.get('skills', []),
            'education': application_data.get('education', ''),
            'coverLetter': application_data.get('coverLetter', ''),
            'status': 'pending',
            'createdAt': datetime.utcnow().isoformat()
        }
        store = self._read_store()
        applications = store.get('applications', [])
        applications.append(application)
        store['applications'] = applications
        self._write_store(store)
        
        # Record activity
        self.record_activity(user_id, 'job_application', {'jobId': job_id, 'applicationId': application_id})
        return application

    def list_applications_for_job(self, job_id):
        """List all applications for a specific job"""
        store = self._read_store()
        applications = [a for a in store.get('applications', []) if a.get('jobId') == job_id]
        return sorted(applications, key=lambda x: x.get('createdAt', ''), reverse=True)

    def list_applications_for_admin(self, admin_id):
        """List all applications for jobs posted by an admin"""
        store = self._read_store()
        admin_jobs = [j.get('jobId') for j in store.get('jobs', []) if j.get('adminId') == admin_id]
        applications = [a for a in store.get('applications', []) if a.get('jobId') in admin_jobs]
        return sorted(applications, key=lambda x: x.get('createdAt', ''), reverse=True)

    def get_application(self, application_id):
        """Get a specific application"""
        store = self._read_store()
        for a in store.get('applications', []):
            if a.get('applicationId') == application_id:
                return a
        return None

    def update_application_status(self, application_id, status, admin_notes=None):
        """Update application status (pending, accepted, rejected, interview_scheduled)"""
        store = self._read_store()
        applications = store.get('applications', [])
        for a in applications:
            if a.get('applicationId') == application_id:
                a['status'] = status
                a['updatedAt'] = datetime.utcnow().isoformat()
                if admin_notes:
                    a['adminNotes'] = admin_notes
                store['applications'] = applications
                self._write_store(store)
                return True
        return False

    def list_user_applications(self, user_id):
        """List all applications by a user"""
        store = self._read_store()
        applications = [a for a in store.get('applications', []) if a.get('userId') == user_id]
        return sorted(applications, key=lambda x: x.get('createdAt', ''), reverse=True)

    # ========== NEW FEATURES: Portfolio, Favorites, Notifications, Gamification ==========
    
    # Portfolio Management
    def update_portfolio(self, user_id, portfolio_data):
        """Update user portfolio with projects, certifications, achievements"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return None
        
        if 'profile' not in user:
            user['profile'] = {}
        if 'portfolio' not in user['profile']:
            user['profile']['portfolio'] = {}
        
        user['profile']['portfolio'].update(portfolio_data)
        user['updatedAt'] = datetime.utcnow().isoformat()
        
        users = [u for u in store.get('users', []) if u.get('userId') != user_id]
        users.append(user)
        store['users'] = users
        self._write_store(store)
        return user['profile']['portfolio']
    
    def get_portfolio(self, user_id):
        """Get user portfolio"""
        user = self.get_user(user_id)
        if user and user.get('profile') and user['profile'].get('portfolio'):
            return user['profile']['portfolio']
        return {}
    
    def get_public_profile(self, user_id):
        """Get public profile for shareable link"""
        user = self.get_user(user_id)
        if not user:
            return None
        
        profile = user.get('profile', {})
        return {
            'userId': user_id,
            'fullName': profile.get('fullName') or profile.get('name', ''),
            'bio': profile.get('bio', ''),
            'currentRole': profile.get('currentRole', ''),
            'targetRole': profile.get('targetRole', ''),
            'skills': profile.get('skills', []),
            'education': profile.get('education', []),
            'portfolio': profile.get('portfolio', {}),
            'photo': profile.get('photo', ''),
            'publicProfileId': user.get('publicProfileId', user_id)
        }
    
    def generate_public_profile_id(self, user_id):
        """Generate a unique public profile ID"""
        import hashlib
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return None
        
        # Create a short hash-based ID
        hash_obj = hashlib.md5(f"{user_id}{user.get('email', '')}".encode())
        public_id = hash_obj.hexdigest()[:12]
        
        user['publicProfileId'] = public_id
        users = [u for u in store.get('users', []) if u.get('userId') != user_id]
        users.append(user)
        store['users'] = users
        self._write_store(store)
        return public_id
    
    def get_user_by_public_id(self, public_id):
        """Get user by public profile ID"""
        store = self._read_store()
        for u in store.get('users', []):
            if u.get('publicProfileId') == public_id:
                return u
        return None
    
    # Saved Jobs & Favorites
    def save_job(self, user_id, job_id):
        """Save/bookmark a job"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return False
        
        if 'savedJobs' not in user:
            user['savedJobs'] = []
        
        if job_id not in user['savedJobs']:
            user['savedJobs'].append(job_id)
            user['updatedAt'] = datetime.utcnow().isoformat()
            
            users = [u for u in store.get('users', []) if u.get('userId') != user_id]
            users.append(user)
            store['users'] = users
            self._write_store(store)
            return True
        return False
    
    def unsave_job(self, user_id, job_id):
        """Remove saved job"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return False
        
        if 'savedJobs' in user and job_id in user['savedJobs']:
            user['savedJobs'].remove(job_id)
            user['updatedAt'] = datetime.utcnow().isoformat()
            
            users = [u for u in store.get('users', []) if u.get('userId') != user_id]
            users.append(user)
            store['users'] = users
            self._write_store(store)
            return True
        return False
    
    def get_saved_jobs(self, user_id):
        """Get list of saved job IDs"""
        user = self.get_user(user_id)
        if user and user.get('savedJobs'):
            return user['savedJobs']
        return []
    
    def save_roadmap(self, user_id, roadmap_id):
        """Save a roadmap to favorites"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return False
        
        if 'savedRoadmaps' not in user:
            user['savedRoadmaps'] = []
        
        if roadmap_id not in user['savedRoadmaps']:
            user['savedRoadmaps'].append(roadmap_id)
            user['updatedAt'] = datetime.utcnow().isoformat()
            
            users = [u for u in store.get('users', []) if u.get('userId') != user_id]
            users.append(user)
            store['users'] = users
            self._write_store(store)
            return True
        return False
    
    def get_saved_roadmaps(self, user_id):
        """Get list of saved roadmap IDs"""
        user = self.get_user(user_id)
        if user and user.get('savedRoadmaps'):
            return user['savedRoadmaps']
        return []
    
    # Notifications
    def create_notification(self, user_id, notification_type, title, message, link=None, metadata=None):
        """Create a notification for a user"""
        store = self._read_store()
        if 'notifications' not in store:
            store['notifications'] = []
        
        notification = {
            'notificationId': str(uuid.uuid4()),
            'userId': user_id,
            'type': notification_type,  # 'job_alert', 'application_update', 'course_reminder', 'achievement', etc.
            'title': title,
            'message': message,
            'link': link,
            'metadata': metadata or {},
            'read': False,
            'createdAt': datetime.utcnow().isoformat()
        }
        
        store['notifications'].append(notification)
        self._write_store(store)
        
        # Send via SNS if configured
        if self.sns and self.sns_topic:
            try:
                user = self.get_user(user_id)
                email = user.get('email', '')
                if email:
                    message_body = f"{title}\n\n{message}"
                    if link:
                        message_body += f"\n\nView: {link}"
                    
                    self.sns.publish(
                        TopicArn=self.sns_topic,
                        Message=message_body,
                        Subject=f"VCC: {title}",
                        MessageAttributes={
                            'email': {'DataType': 'String', 'StringValue': email}
                        }
                    )
            except Exception:
                pass  # Fail silently if SNS not configured
        
        return notification
    
    def get_notifications(self, user_id, unread_only=False):
        """Get notifications for a user"""
        store = self._read_store()
        notifications = [n for n in store.get('notifications', []) if n.get('userId') == user_id]
        
        if unread_only:
            notifications = [n for n in notifications if not n.get('read', False)]
        
        return sorted(notifications, key=lambda x: x.get('createdAt', ''), reverse=True)
    
    def mark_notification_read(self, notification_id, user_id):
        """Mark a notification as read"""
        store = self._read_store()
        notifications = store.get('notifications', [])
        changed = False
        
        for n in notifications:
            if n.get('notificationId') == notification_id and n.get('userId') == user_id:
                n['read'] = True
                n['readAt'] = datetime.utcnow().isoformat()
                changed = True
        
        if changed:
            store['notifications'] = notifications
            self._write_store(store)
        return changed
    
    def mark_all_notifications_read(self, user_id):
        """Mark all notifications as read for a user"""
        store = self._read_store()
        notifications = store.get('notifications', [])
        changed = False
        
        for n in notifications:
            if n.get('userId') == user_id and not n.get('read', False):
                n['read'] = True
                n['readAt'] = datetime.utcnow().isoformat()
                changed = True
        
        if changed:
            store['notifications'] = notifications
            self._write_store(store)
        return changed
    
    # Gamification System
    def award_xp(self, user_id, amount, reason=None):
        """Award XP to a user"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return None
        
        if 'gamification' not in user:
            user['gamification'] = {
                'xp': 0,
                'level': 1,
                'badges': [],
                'streak': 0,
                'lastLoginDate': None,
                'achievements': []
            }
        
        user['gamification']['xp'] = user['gamification'].get('xp', 0) + amount
        
        # Calculate level (100 XP per level)
        new_level = (user['gamification']['xp'] // 100) + 1
        old_level = user['gamification'].get('level', 1)
        user['gamification']['level'] = new_level
        
        # Level up notification
        if new_level > old_level:
            self.create_notification(
                user_id, 'achievement', 
                f'Level Up! 🎉', 
                f'You reached level {new_level}! Keep up the great work!',
                '/dashboard'
            )
        
        user['updatedAt'] = datetime.utcnow().isoformat()
        
        users = [u for u in store.get('users', []) if u.get('userId') != user_id]
        users.append(user)
        store['users'] = users
        self._write_store(store)
        
        return user['gamification']
    
    def award_badge(self, user_id, badge_name, badge_icon='🏅', description=None):
        """Award a badge to a user"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return False
        
        if 'gamification' not in user:
            user['gamification'] = {'badges': [], 'xp': 0, 'level': 1, 'streak': 0}
        
        badges = user['gamification'].get('badges', [])
        badge_exists = any(b.get('name') == badge_name for b in badges)
        
        if not badge_exists:
            badge = {
                'name': badge_name,
                'icon': badge_icon,
                'description': description or f'Achievement: {badge_name}',
                'earnedAt': datetime.utcnow().isoformat()
            }
            badges.append(badge)
            user['gamification']['badges'] = badges
            user['updatedAt'] = datetime.utcnow().isoformat()
            
            # Award XP for badge
            self.award_xp(user_id, 50, f'Badge: {badge_name}')
            
            # Notification
            self.create_notification(
                user_id, 'achievement',
                f'New Badge Earned! {badge_icon}',
                f'You earned the "{badge_name}" badge!',
                '/dashboard'
            )
            
            users = [u for u in store.get('users', []) if u.get('userId') != user_id]
            users.append(user)
            store['users'] = users
            self._write_store(store)
            return True
        return False
    
    def update_streak(self, user_id):
        """Update login streak"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return None
        
        if 'gamification' not in user:
            user['gamification'] = {'streak': 0, 'lastLoginDate': None, 'xp': 0, 'level': 1}
        
        today = datetime.utcnow().date().isoformat()
        last_login = user['gamification'].get('lastLoginDate')
        
        if last_login == today:
            # Already logged in today
            return user['gamification']
        
        if last_login:
            from datetime import date, timedelta
            last_date = datetime.fromisoformat(last_login).date()
            today_date = date.today()
            
            if (today_date - last_date).days == 1:
                # Consecutive day
                user['gamification']['streak'] = user['gamification'].get('streak', 0) + 1
            elif (today_date - last_date).days > 1:
                # Streak broken
                user['gamification']['streak'] = 1
            else:
                # Same day, no change
                return user['gamification']
        else:
            # First login
            user['gamification']['streak'] = 1
        
        user['gamification']['lastLoginDate'] = today
        user['updatedAt'] = datetime.utcnow().isoformat()
        
        # Award XP for daily login
        self.award_xp(user_id, 10, 'Daily login')
        
        # Streak milestones
        streak = user['gamification']['streak']
        if streak in [7, 30, 100]:
            self.award_badge(user_id, f'{streak} Day Streak', '🔥', f'Logged in for {streak} consecutive days!')
        
        users = [u for u in store.get('users', []) if u.get('userId') != user_id]
        users.append(user)
        store['users'] = users
        self._write_store(store)
        
        return user['gamification']
    
    def get_gamification_stats(self, user_id):
        """Get gamification stats for a user"""
        user = self.get_user(user_id)
        if user and user.get('gamification'):
            return user['gamification']
        return {'xp': 0, 'level': 1, 'badges': [], 'streak': 0, 'achievements': []}
    
    # Resume Builder
    def save_resume(self, user_id, resume_data):
        """Save resume data"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return None
        
        if 'resumes' not in user:
            user['resumes'] = []
        
        resume = {
            'resumeId': str(uuid.uuid4()),
            'name': resume_data.get('name', 'My Resume'),
            'template': resume_data.get('template', 'modern'),
            'sections': resume_data.get('sections', {}),
            'createdAt': datetime.utcnow().isoformat(),
            'updatedAt': datetime.utcnow().isoformat()
        }
        
        user['resumes'].append(resume)
        user['updatedAt'] = datetime.utcnow().isoformat()
        
        users = [u for u in store.get('users', []) if u.get('userId') != user_id]
        users.append(user)
        store['users'] = users
        self._write_store(store)
        
        return resume
    
    def get_resumes(self, user_id):
        """Get all resumes for a user"""
        user = self.get_user(user_id)
        if user and user.get('resumes'):
            return user['resumes']
        return []
    
    def get_resume(self, user_id, resume_id):
        """Get a specific resume"""
        resumes = self.get_resumes(user_id)
        for r in resumes:
            if r.get('resumeId') == resume_id:
                return r
        return None
    
    def delete_resume(self, user_id, resume_id):
        """Delete a resume"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user or not user.get('resumes'):
            return False
        
        user['resumes'] = [r for r in user['resumes'] if r.get('resumeId') != resume_id]
        user['updatedAt'] = datetime.utcnow().isoformat()
        
        users = [u for u in store.get('users', []) if u.get('userId') != user_id]
        users.append(user)
        store['users'] = users
        self._write_store(store)
        return True

    # ========== SOCIAL NETWORKING & MENTORSHIP ==========
    
    def send_connection_request(self, from_user_id, to_user_id, message=None):
        """Send a connection request"""
        store = self._read_store()
        if 'connections' not in store:
            store['connections'] = []
        
        # Check if already connected or request exists
        existing = [c for c in store['connections'] 
                   if (c.get('fromUserId') == from_user_id and c.get('toUserId') == to_user_id) or
                      (c.get('fromUserId') == to_user_id and c.get('toUserId') == from_user_id)]
        
        if existing:
            return None
        
        connection = {
            'connectionId': str(uuid.uuid4()),
            'fromUserId': from_user_id,
            'toUserId': to_user_id,
            'message': message,
            'status': 'pending',
            'createdAt': datetime.utcnow().isoformat()
        }
        
        store['connections'].append(connection)
        self._write_store(store)
        
        # Send notification
        self.create_notification(
            to_user_id, 'connection_request',
            'New Connection Request',
            f'You have a new connection request',
            '/connections'
        )
        
        return connection
    
    def accept_connection(self, connection_id, user_id):
        """Accept a connection request"""
        store = self._read_store()
        connections = store.get('connections', [])
        
        for conn in connections:
            if conn.get('connectionId') == connection_id and conn.get('toUserId') == user_id:
                conn['status'] = 'accepted'
                conn['acceptedAt'] = datetime.utcnow().isoformat()
                store['connections'] = connections
                self._write_store(store)
                
                # Notify the requester
                self.create_notification(
                    conn.get('fromUserId'), 'connection_accepted',
                    'Connection Accepted',
                    'Your connection request was accepted!',
                    '/connections'
                )
                return True
        return False
    
    def get_connections(self, user_id):
        """Get all connections for a user"""
        store = self._read_store()
        connections = store.get('connections', [])
        
        user_connections = []
        for conn in connections:
            if conn.get('fromUserId') == user_id or conn.get('toUserId') == user_id:
                if conn.get('status') == 'accepted':
                    other_user_id = conn.get('toUserId') if conn.get('fromUserId') == user_id else conn.get('fromUserId')
                    other_user = self.get_user(other_user_id)
                    if other_user:
                        user_connections.append({
                            'connection': conn,
                            'user': other_user
                        })
        
        return user_connections
    
    def find_mentors(self, user_id, career_field=None):
        """Find potential mentors based on career field"""
        user = self.get_user(user_id)
        if not user:
            return []
        
        target_role = (user.get('profile', {}).get('targetRole') or career_field or '').lower()
        
        store = self._read_store()
        all_users = store.get('users', [])
        
        # Find users with matching target role who are more experienced
        mentors = []
        for u in all_users:
            if u.get('userId') == user_id:
                continue
            
            profile = u.get('profile', {})
            user_role = (profile.get('targetRole') or profile.get('currentRole') or '').lower()
            
            if target_role and target_role in user_role or user_role in target_role:
                # Check if they have more experience (more activities, roadmaps, etc.)
                activities = [a for a in store.get('activities', []) if a.get('userId') == u.get('userId')]
                completed = [a for a in activities if a.get('status') == 'completed']
                
                if len(completed) > 5:  # Has significant experience
                    mentors.append({
                        'user': u,
                        'matchScore': len(completed),
                        'completedActivities': len(completed)
                    })
        
        # Sort by match score
        mentors.sort(key=lambda x: x['matchScore'], reverse=True)
        return mentors[:10]  # Top 10 mentors
    
    def create_forum_post(self, user_id, career_field, title, content):
        """Create a forum post"""
        store = self._read_store()
        if 'forum_posts' not in store:
            store['forum_posts'] = []
        
        post = {
            'postId': str(uuid.uuid4()),
            'userId': user_id,
            'careerField': career_field,
            'title': title,
            'content': content,
            'likes': 0,
            'comments': [],
            'createdAt': datetime.utcnow().isoformat()
        }
        
        store['forum_posts'].append(post)
        self._write_store(store)
        return post
    
    def get_forum_posts(self, career_field=None):
        """Get forum posts, optionally filtered by career field"""
        store = self._read_store()
        posts = store.get('forum_posts', [])
        
        if career_field:
            posts = [p for p in posts if p.get('careerField', '').lower() == career_field.lower()]
        
        # Add user info to each post
        for post in posts:
            user = self.get_user(post.get('userId'))
            post['author'] = {
                'name': user.get('profile', {}).get('fullName') if user else 'Anonymous',
                'role': user.get('profile', {}).get('targetRole') if user else ''
            }
        
        return sorted(posts, key=lambda x: x.get('createdAt', ''), reverse=True)
    
    # ========== AI CAREER MATCHING ==========
    
    def career_personality_test(self, user_id, answers):
        """Process personality test and return career matches"""
        if self.groq_client:
            try:
                answers_text = json.dumps(answers)
                prompt = f"""Based on these personality test answers, suggest 5 career matches with fit scores:

Answers: {answers_text}

Provide JSON response:
{{
  "personality_type": "Type description",
  "careers": [
    {{
      "career": "Career name",
      "fit_score": 85,
      "reason": "Why this career matches",
      "skills_needed": ["skill1", "skill2"],
      "growth_potential": "High/Medium/Low"
    }}
  ],
  "insights": "Overall personality insights"
}}"""
                
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {'role': 'system', 'content': 'You are a career counselor expert in personality assessments and career matching.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    model=os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant'),
                    temperature=0.7,
                    max_tokens=2000,
                    response_format={"type": "json_object"}
                )
                
                result = json.loads(chat_completion.choices[0].message.content)
                return result
            except Exception as e:
                pass
        
        # Fallback
        return {
            "personality_type": "Analytical & Creative",
            "careers": [
                {"career": "Software Engineer", "fit_score": 85, "reason": "Matches analytical thinking", "skills_needed": ["Programming", "Problem-solving"], "growth_potential": "High"},
                {"career": "Data Analyst", "fit_score": 80, "reason": "Good for detail-oriented people", "skills_needed": ["Analytics", "Statistics"], "growth_potential": "High"}
            ],
            "insights": "You have a balanced personality suitable for technical and creative roles."
        }
    
    # ========== SALARY NEGOTIATION ASSISTANT ==========
    
    def get_salary_negotiation_tips(self, role, current_salary=None, offer_amount=None, location=None):
        """Get AI-powered salary negotiation tips"""
        if self.groq_client:
            try:
                context = f"Role: {role}"
                if location:
                    context += f", Location: {location}"
                if current_salary:
                    context += f", Current Salary: {current_salary}"
                if offer_amount:
                    context += f", Offer Amount: {offer_amount}"
                
                prompt = f"""Provide comprehensive salary negotiation advice for {context}. Include:

1. Market salary range for this role
2. Negotiation strategies
3. What to say/avoid
4. Counter-offer suggestions
5. Benefits to negotiate beyond salary

Format as JSON:
{{
  "market_range": "Salary range",
  "strategies": ["strategy1", "strategy2"],
  "phrases_to_use": ["phrase1", "phrase2"],
  "phrases_to_avoid": ["phrase1", "phrase2"],
  "counter_offer_suggestions": "Suggestions",
  "benefits_to_negotiate": ["benefit1", "benefit2"],
  "evaluation": "Is the offer fair? Why?"
}}"""
                
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {'role': 'system', 'content': 'You are a salary negotiation expert with knowledge of market rates and negotiation tactics.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    model=os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant'),
                    temperature=0.7,
                    max_tokens=2000,
                    response_format={"type": "json_object"}
                )
                
                result = json.loads(chat_completion.choices[0].message.content)
                return result
            except Exception as e:
                pass
        
        # Fallback
        return {
            "market_range": "$60,000 - $90,000",
            "strategies": ["Research market rates", "Highlight your value", "Be confident but respectful"],
            "phrases_to_use": ["Based on my research...", "I'm excited about this opportunity..."],
            "phrases_to_avoid": ["I need more money", "That's not enough"],
            "counter_offer_suggestions": "Consider negotiating 10-15% above the initial offer",
            "benefits_to_negotiate": ["Health insurance", "Remote work", "Professional development"],
            "evaluation": "Evaluate based on market rates and your experience level"
        }
    
    # ========== COMPANY INSIGHTS ==========
    
    def add_company_review(self, user_id, company_name, review_data):
        """Add a company review"""
        store = self._read_store()
        if 'company_reviews' not in store:
            store['company_reviews'] = []
        
        review = {
            'reviewId': str(uuid.uuid4()),
            'userId': user_id,
            'companyName': company_name,
            'rating': review_data.get('rating', 5),
            'pros': review_data.get('pros', []),
            'cons': review_data.get('cons', []),
            'culture': review_data.get('culture', ''),
            'workLifeBalance': review_data.get('workLifeBalance', ''),
            'interviewExperience': review_data.get('interviewExperience', ''),
            'createdAt': datetime.utcnow().isoformat()
        }
        
        store['company_reviews'].append(review)
        self._write_store(store)
        return review
    
    def get_company_reviews(self, company_name):
        """Get reviews for a company"""
        store = self._read_store()
        reviews = [r for r in store.get('company_reviews', []) if r.get('companyName', '').lower() == company_name.lower()]
        
        # Add user info
        for review in reviews:
            user = self.get_user(review.get('userId'))
            review['author'] = user.get('profile', {}).get('fullName') if user else 'Anonymous'
        
        return sorted(reviews, key=lambda x: x.get('createdAt', ''), reverse=True)
    
    def get_company_insights(self, company_name):
        """Get aggregated company insights"""
        reviews = self.get_company_reviews(company_name)
        
        if not reviews:
            return {
                'companyName': company_name,
                'averageRating': 0,
                'totalReviews': 0,
                'insights': 'No reviews yet'
            }
        
        avg_rating = sum(r.get('rating', 0) for r in reviews) / len(reviews)
        
        # Aggregate pros and cons
        all_pros = []
        all_cons = []
        for r in reviews:
            all_pros.extend(r.get('pros', []))
            all_cons.extend(r.get('cons', []))
        
        return {
            'companyName': company_name,
            'averageRating': round(avg_rating, 1),
            'totalReviews': len(reviews),
            'commonPros': list(set(all_pros))[:5],
            'commonCons': list(set(all_cons))[:5],
            'reviews': reviews
        }
    
    # ========== ENHANCED AI CHAT WITH BETTER CONTEXT ==========
    
    def enhanced_chat(self, user_id, message, context=None):
        """Enhanced chat with better context awareness"""
        user = self.get_user(user_id)
        user_profile = user.get('profile', {}) if user else {}
        
        # Build context
        context_info = []
        if user_profile.get('targetRole'):
            context_info.append(f"User's target career: {user_profile.get('targetRole')}")
        if user_profile.get('currentRole'):
            context_info.append(f"User's current role: {user_profile.get('currentRole')}")
        
        # Get recent activities
        activities = self.list_user_activities(user_id)
        completed = [a for a in activities if a.get('status') == 'completed']
        if completed:
            context_info.append(f"User has completed {len(completed)} activities")
        
        # Get roadmaps
        roadmaps = self.list_roadmaps_for_user(user_id)
        if roadmaps:
            context_info.append(f"User has {len(roadmaps)} roadmaps")
        
        context_str = "\n".join(context_info) if context_info else "No specific context available"
        
        if self.groq_client:
            try:
                system_prompt = f"""You are an expert career counselor AI assistant. You provide personalized, accurate, and actionable career guidance.

User Context:
{context_str}

Guidelines:
- Provide specific, actionable advice
- Reference the user's career goals when relevant
- Be encouraging and supportive
- Give concrete examples and steps
- If asked about careers, provide detailed information about requirements, skills, salary, growth prospects
- For interview questions, provide STAR method examples
- For resume help, give specific improvement suggestions
- Always be professional and helpful"""
                
                chat_completion = self.groq_client.chat.completions.create(
                    messages=[
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': message}
                    ],
                    model=os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant'),
                    temperature=0.7,
                    max_tokens=1500
                )
                
                response = chat_completion.choices[0].message.content
                self.record_activity(user_id, 'enhanced_chat', {'message': message, 'reply': response})
                return response
            except Exception as e:
                pass
        
        # Fallback
        return self.chat_with_provider(user_id, message)
    
    # ========== LEARNING PATHS WITH MILESTONES ==========
    
    def create_learning_path(self, user_id, career_field, milestones):
        """Create a structured learning path with milestones"""
        store = self._read_store()
        if 'learning_paths' not in store:
            store['learning_paths'] = []
        
        path = {
            'pathId': str(uuid.uuid4()),
            'userId': user_id,
            'careerField': career_field,
            'milestones': milestones,
            'progress': 0,
            'currentMilestone': 0,
            'createdAt': datetime.utcnow().isoformat()
        }
        
        store['learning_paths'].append(path)
        self._write_store(store)
        return path
    
    def complete_milestone(self, user_id, path_id, milestone_index):
        """Mark a milestone as complete"""
        store = self._read_store()
        paths = store.get('learning_paths', [])
        
        for path in paths:
            if path.get('pathId') == path_id and path.get('userId') == user_id:
                milestones = path.get('milestones', [])
                if milestone_index < len(milestones):
                    milestones[milestone_index]['completed'] = True
                    milestones[milestone_index]['completedAt'] = datetime.utcnow().isoformat()
                    
                    # Update progress
                    completed = sum(1 for m in milestones if m.get('completed'))
                    path['progress'] = int((completed / len(milestones)) * 100)
                    path['currentMilestone'] = min(milestone_index + 1, len(milestones) - 1)
                    
                    # Award XP and badge for completion
                    self.award_xp(user_id, 50, f'Completed milestone: {milestones[milestone_index].get("title")}')
                    
                    if path['progress'] == 100:
                        self.award_badge(user_id, 'Path Master', '🏆', f'Completed learning path for {path.get("careerField")}')
                    
                    store['learning_paths'] = paths
                    self._write_store(store)
                    return True
        return False
    
    def get_learning_paths(self, user_id):
        """Get all learning paths for a user"""
        store = self._read_store()
        return [p for p in store.get('learning_paths', []) if p.get('userId') == user_id]
    
    # ========== REFERRAL PROGRAM ==========
    
    def create_referral_code(self, user_id):
        """Create a referral code for a user"""
        store = self._read_store()
        user = self.get_user(user_id)
        if not user:
            return None
        
        # Generate unique code
        import hashlib
        code = hashlib.md5(f"{user_id}{user.get('email', '')}".encode()).hexdigest()[:8].upper()
        
        if 'referrals' not in user:
            user['referrals'] = {'code': code, 'count': 0, 'rewards': []}
        else:
            user['referrals']['code'] = code
        
        users = [u for u in store.get('users', []) if u.get('userId') != user_id]
        users.append(user)
        store['users'] = users
        self._write_store(store)
        
        return code
    
    def use_referral_code(self, new_user_id, referral_code):
        """Use a referral code (when new user signs up)"""
        store = self._read_store()
        
        # Find user with this referral code
        for user in store.get('users', []):
            if user.get('referrals', {}).get('code') == referral_code.upper():
                # Award rewards
                user['referrals']['count'] = user['referrals'].get('count', 0) + 1
                user['referrals']['rewards'].append({
                    'referredUserId': new_user_id,
                    'rewardedAt': datetime.utcnow().isoformat()
                })
                
                # Award XP to referrer
                self.award_xp(user.get('userId'), 100, 'Referred a friend')
                
                # Award XP to new user
                self.award_xp(new_user_id, 50, 'Signed up with referral code')
                
                # Award badges
                if user['referrals']['count'] >= 5:
                    self.award_badge(user.get('userId'), 'Super Connector', '🤝', 'Referred 5+ friends!')
                
                users = [u for u in store.get('users', []) if u.get('userId') != user.get('userId')]
                users.append(user)
                store['users'] = users
                self._write_store(store)
                return True
        

        return False
