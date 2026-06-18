from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_USER = {
    "id": "demo-user",
    "email": "demo@buddystudy.local",
    "display_name": "Demo Learner",
    "avatar_url": "",
    "role": "student",
}

DEFAULT_STATS = {
    "level": 12,
    "xp": 680,
    "coins": 0,
    "streak": 12,
    "streak_count": 12,
    "last_streak_date": None,
    "last_login_reward_date": None,
    "total_quizzes": 32,
    "total_correct_answers": 81,
    "total_study_minutes": 1120,
}

NEW_USER_STATS = {
    "level": 0,
    "xp": 0,
    "coins": 0,
    "streak": 0,
    "streak_count": 0,
    "last_streak_date": None,
    "last_login_reward_date": None,
    "total_quizzes": 0,
    "total_correct_answers": 0,
    "total_study_minutes": 0,
}

BUDDIES = [
    {
        "id": "chasam",
        "name": "Chasam",
        "role": "Mascot mochi hong",
        "type": "Mascot mochi hong",
        "emoji": "??",
        "gradient": "from-pink-50 via-rose-50 to-orange-50",
        "description": "Buddy mascot de thuong, duoc dung lam nhan vat 2D chinh trong Buddy Room.",
        "personality": "Am ap, nhe nhang, hop voi khong gian phong hoc va cac skin reward.",
        "avatar_url": "/buddies/chasam/icon.png",
        "fallbackImage": "/buddies/chasam/icon.png",
        "accent": "rose",
        "default_mood": "happy",
        "mood": "happy",
        "rarity": "common",
        "tags": ["Cute", "Reward", "Room", "Daily"],
        "skills": ["Dong vien nhe nhang", "Phong hoc cozy", "Mo khoa skin reward"],
    },
    {
        "id": "lumi",
        "name": "Lumi",
        "role": "Robot AI Buddy",
        "type": "Robot AI Buddy",
        "emoji": "🤖",
        "gradient": "from-cyan-50 via-white to-sky-50",
        "description": "Phân tích tiến độ, gợi ý bài học và nhắc bạn giữ nhịp học đều.",
        "personality": "Thông minh, năng động, nhiều năng lượng công nghệ.",
        "avatar_url": "/buddies/lumi.jpg",
        "fallbackImage": "/buddies/lumi.jpg",
        "accent": "cyan",
        "default_mood": "happy",
        "mood": "happy",
        "rarity": "common",
        "tags": ["Data Coach", "AI", "Focus", "Tech"],
        "skills": ["Phân tích tiến độ", "Gợi ý lộ trình thông minh", "Nhắc học theo streak"],
    },
    {
        "id": "miu",
        "name": "Miu",
        "role": "Mèo học thuật",
        "type": "Mèo học thuật",
        "emoji": "🐱",
        "gradient": "from-violet-50 via-pink-50 to-white",
        "description": "Đồng hành nhẹ nhàng, động viên bạn sau mỗi quiz và nhiệm vụ học tập.",
        "personality": "Ấm áp, kiên nhẫn, phù hợp học đều mỗi ngày.",
        "avatar_url": "/buddies/miu.jpg",
        "fallbackImage": "/buddies/miu.jpg",
        "accent": "violet",
        "default_mood": "happy",
        "mood": "happy",
        "rarity": "common",
        "tags": ["Gentle Push", "Cute", "Support", "Daily"],
        "skills": ["Động viên sau quiz", "Gợi ý ôn tập", "Nhắc học nhẹ nhàng"],
    },
    {
        "id": "owly",
        "name": "Owly",
        "role": "Cú thông thái",
        "type": "Cú thông thái",
        "emoji": "🦉",
        "gradient": "from-amber-50 via-orange-50 to-white",
        "description": "Tập trung vào ghi nhớ sâu, ôn tập thông minh và học theo chủ đề.",
        "personality": "Điềm tĩnh, uyên bác, luôn biết phần nào cần ôn lại.",
        "avatar_url": "/buddies/owly.jpg",
        "fallbackImage": "/buddies/owly.jpg",
        "accent": "amber",
        "default_mood": "thinking",
        "mood": "thinking",
        "rarity": "common",
        "tags": ["Deep Recall", "Mentor", "Focus", "Study"],
        "skills": ["Ôn tập ghi nhớ sâu", "Giải thích theo chủ đề", "Nhắc lịch review"],
    },
    {
        "id": "nova",
        "name": "Nova",
        "role": "Mentor AI nam",
        "type": "Mentor AI nam",
        "emoji": "🧑‍💻",
        "gradient": "from-indigo-50 via-blue-50 to-white",
        "description": "Mentor rõ ràng, phù hợp học viên thích mục tiêu cụ thể.",
        "personality": "Tập trung, logic và luôn chia bài học thành checklist dễ làm.",
        "avatar_url": "/buddies/nova.jpg",
        "fallbackImage": "/buddies/nova.jpg",
        "accent": "indigo",
        "default_mood": "focus",
        "mood": "focus",
        "rarity": "common",
        "tags": ["Sprint Plan", "Mentor", "Focus", "AI"],
        "skills": ["Coaching theo mục tiêu", "Checklist học tập", "Tối ưu thời gian học"],
    },
    {
        "id": "ivy",
        "name": "Ivy",
        "role": "Mentor AI nữ",
        "type": "Mentor AI nữ",
        "emoji": "👩‍🎓",
        "gradient": "from-rose-50 via-violet-50 to-white",
        "description": "Gợi ý học tập cân bằng, thân thiện và theo sát cảm xúc học tập.",
        "personality": "Tinh tế, hỗ trợ, biết cân bằng giữa kỷ luật và cảm xúc.",
        "avatar_url": "/buddies/ivy.jpg",
        "fallbackImage": "/buddies/ivy.jpg",
        "accent": "rose",
        "default_mood": "calm",
        "mood": "calm",
        "rarity": "common",
        "tags": ["Mood Care", "Mentor", "Cute", "Support"],
        "skills": ["Cân bằng cảm xúc", "Gợi ý học mềm mại", "Theo dõi động lực"],
    },
    {
        "id": "tree",
        "name": "Groot",
        "role": "Guardian mầm xanh",
        "type": "Guardian mầm xanh",
        "emoji": "🌳",
        "gradient": "from-emerald-50 via-green-50 to-white",
        "description": "Buddy hướng growth dài hạn, nhắc bạn học đều và tiến bộ bền vững.",
        "personality": "Điềm đạm, ấm áp và kiên trì.",
        "avatar_url": "/buddies/groot.jpg",
        "fallbackImage": "/buddies/groot.jpg",
        "accent": "emerald",
        "default_mood": "idle",
        "mood": "idle",
        "rarity": "common",
        "tags": ["Groot Mode", "Growth", "Focus", "Daily"],
        "skills": ["Theo dõi thói quen", "Nuôi streak dài hạn", "Nhắc học bền vững"],
    },
]

MISSIONS = [
    {"id": "daily-quiz", "type": "daily", "target_type": "quiz_completed", "target_value": 1, "title": "Hoàn thành 1 quiz Grammar", "description": "Làm quiz để kiểm tra kiến thức hôm nay.", "reward_xp": 20, "reward_coins": 5},
    {"id": "vocab-review", "type": "daily", "target_type": "study_minutes", "target_value": 15, "title": "Ôn tập 15 phút", "description": "Ôn lại các từ đã sai trong 3 ngày gần nhất.", "reward_xp": 15, "reward_coins": 0},
    {"id": "read-lesson", "type": "daily", "target_type": "study_minutes", "target_value": 20, "title": "Đọc 1 bài học ngắn", "description": "Hoàn thành bài đọc về Present Perfect.", "reward_xp": 10, "reward_coins": 0},
    {"id": "weekly-streak", "type": "weekly", "target_type": "login_streak", "target_value": 5, "title": "Giữ streak 5 ngày", "description": "Học ít nhất 15 phút mỗi ngày trong tuần.", "reward_xp": 80, "reward_coins": 10},
    {"id": "achievement-first", "type": "achievement", "target_type": "quiz_completed", "target_value": 1, "title": "Quiz đầu tiên", "description": "Hoàn thành quiz đầu tiên với độ chính xác trên 70%.", "reward_xp": 30, "reward_coins": 5},
]

QUIZZES = [
    {
        "id": "grammar-01",
        "title": "Grammar Quiz",
        "description": "Present Perfect basics",
        "level": 1,
        "topic": "Present Perfect",
        "reward_xp": 20,
        "reward_coins": 5,
        "questions": [
            {
                "id": "grammar-01-q1",
                "question_text": "Choose the correct sentence.",
                "explanation": "Present perfect uses have/has + past participle.",
                "order_index": 1,
                "options": [
                    ("grammar-01-q1-a", "I have finished my homework.", True),
                    ("grammar-01-q1-b", "I has finished my homework.", False),
                    ("grammar-01-q1-c", "I finished have my homework.", False),
                    ("grammar-01-q1-d", "I have finish my homework.", False),
                ],
            },
            {
                "id": "grammar-01-q2",
                "question_text": "What does 'already' usually express?",
                "explanation": "Already often means an action is completed sooner than expected.",
                "order_index": 2,
                "options": [
                    ("grammar-01-q2-a", "A future plan", False),
                    ("grammar-01-q2-b", "A completed action", True),
                    ("grammar-01-q2-c", "A habit", False),
                    ("grammar-01-q2-d", "A comparison", False),
                ],
            },
            {
                "id": "grammar-01-q3",
                "question_text": "Pick the best answer: She ___ visited London.",
                "explanation": "She is third-person singular, so use has.",
                "order_index": 3,
                "options": [
                    ("grammar-01-q3-a", "have", False),
                    ("grammar-01-q3-b", "has", True),
                    ("grammar-01-q3-c", "is", False),
                    ("grammar-01-q3-d", "does", False),
                ],
            },
        ],
    }
]

ACHIEVEMENTS = [
    {"id": "starter", "title": "Starter Scholar", "description": "Complete your first quiz.", "icon": "Medal", "condition_type": "quiz_completed", "condition_value": 1, "reward_xp": 20, "reward_coins": 5},
    {"id": "streak", "title": "7-Day Focus", "description": "Reach a 7-day learning streak.", "icon": "Flame", "condition_type": "login_streak", "condition_value": 7, "reward_xp": 50, "reward_coins": 10},
    {"id": "grammar", "title": "Grammar Explorer", "description": "Complete 3 grammar quizzes.", "icon": "Award", "condition_type": "quiz_completed", "condition_value": 3, "reward_xp": 60, "reward_coins": 15},
]

COMPANION_ACTIONS = ["idle", "relax", "thinking", "lookAround", "clapping", "goodbye", "jump", "angry", "blush", "sad", "sleepy", "surprised", "greeting", "peace", "shoot", "spin", "pose", "catwalk", "squat", "rasengan"]

COMPANION_MODELS = [
    {"id": "changli-vrm", "name": "Changli", "description": "Model VRM Changli.", "model_url": "/vrm-models/Changli.vrm", "thumbnail_url": "", "rarity": "common", "price": 1, "tags": ["shop"], "actions": COMPANION_ACTIONS, "accent": "rose", "source": "shop"},
    {"id": "yinlin-vrm", "name": "Yinlin", "description": "Model VRM Yinlin.", "model_url": "/vrm-models/Yinlin.vrm", "thumbnail_url": "", "rarity": "common", "price": 1, "tags": ["shop"], "actions": COMPANION_ACTIONS, "accent": "violet", "source": "shop"},
    {"id": "carlotta-vrm", "name": "Carlotta", "description": "Model VRM Carlotta.", "model_url": "/vrm-models/Carlotta.vrm", "thumbnail_url": "", "rarity": "common", "price": 1, "tags": ["shop"], "actions": COMPANION_ACTIONS, "accent": "cyan", "source": "shop"},
    {"id": "naruto-vrm", "name": "Naruto", "description": "Model VRM Naruto.", "model_url": "/vrm-models/naruto.vrm", "thumbnail_url": "", "rarity": "common", "price": 1, "tags": ["shop"], "actions": COMPANION_ACTIONS, "accent": "amber", "source": "shop"},
    {"id": "vita-vrm", "name": "Vivi", "description": "Model VRM mascot.", "model_url": "/vrm-models/vita.vrm", "thumbnail_url": "", "rarity": "common", "price": 1, "tags": ["shop"], "actions": COMPANION_ACTIONS, "accent": "cyan", "source": "shop"},
    {"id": "buddy-1-vrm", "name": "Luna", "description": "Achievement VRM model.", "model_url": "/vrm-models/6493143135142452442.vrm", "thumbnail_url": "", "rarity": "achievement", "price": 0, "tags": ["achievement"], "actions": COMPANION_ACTIONS, "accent": "violet", "source": "achievement"},
]

ROOM_BACKGROUNDS = [
    {"id": "cozy-night", "name": "Đêm ấm áp", "description": "Góc học đêm với ánh sao dịu.", "image_url": "/backgrounds/cozy-night.png", "thumbnail_url": "/backgrounds/cozy-night.png", "price": 1, "accent": "indigo"},
    {"id": "study-room-sunlit", "name": "Phòng học nắng sớm", "description": "Không gian học tập ấm áp.", "image_url": "/backgrounds/study-room-sunlit.png", "thumbnail_url": "/backgrounds/study-room-sunlit.png", "price": 1, "accent": "amber"},
    {"id": "pastel-study", "name": "Pastel dịu nhẹ", "description": "Không gian pastel sáng.", "image_url": "/backgrounds/pastel-study.png", "thumbnail_url": "/backgrounds/pastel-study.png", "price": 1, "accent": "violet"},
    {"id": "forest-path-bright", "name": "Lối rừng tươi sáng", "description": "Con đường xanh mát giữa rừng.", "image_url": "/backgrounds/forest-path-bright.png", "thumbnail_url": "/backgrounds/forest-path-bright.png", "price": 1, "accent": "emerald"},
    {"id": "neon-tech", "name": "Phòng AI neon", "description": "Phong cách công nghệ xanh tím.", "image_url": "/backgrounds/neon-tech.png", "thumbnail_url": "/backgrounds/neon-tech.png", "price": 1, "accent": "cyan"},
    {"id": "lake-meadow-bright", "name": "Hồ cỏ ban mai", "description": "Mặt hồ và đồng cỏ rộng mở.", "image_url": "/backgrounds/lake-meadow-bright.png", "thumbnail_url": "/backgrounds/lake-meadow-bright.png", "price": 1, "accent": "cyan"},
    {"id": "cozy-lounge", "name": "Góc đọc sách", "description": "Không gian thư giãn với ghế lười.", "image_url": "/backgrounds/cozy-lounge.png", "thumbnail_url": "/backgrounds/cozy-lounge.png", "price": 1, "accent": "amber"},
]

