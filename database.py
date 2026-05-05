# database.py
from sqlalchemy import create_engine, Column, BigInteger, String, Integer, DateTime, Boolean, ForeignKey, Float
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import datetime

Base = declarative_base()

# ---------------------- Модели таблиц ----------------------
class User(Base):
    __tablename__ = 'users'
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    registered_at = Column(DateTime, default=datetime.datetime.utcnow)

    progress = relationship('UserProgress', back_populates='user')
    attempts = relationship('Attempt', back_populates='user')

class Topic(Base):
    __tablename__ = 'topics'
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False, unique=True)
    grade = Column(Integer, nullable=False)          # 8 или 9
    order = Column(Integer, nullable=False)          # порядок изучения
    is_active = Column(Boolean, default=True)

    progress = relationship('UserProgress', back_populates='topic')
    attempts = relationship('Attempt', back_populates='topic')

class UserProgress(Base):
    __tablename__ = 'user_progress'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    topic_id = Column(Integer, ForeignKey('topics.id'))
    status = Column(String(20), default='not_started')  # not_started, in_progress, passed, failed
    score = Column(Float, default=0.0)                  # накопленный балл (с учётом веса попыток)
    last_attempt_at = Column(DateTime, nullable=True)

    user = relationship('User', back_populates='progress')
    topic = relationship('Topic', back_populates='progress')

class Attempt(Base):
    __tablename__ = 'attempts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    topic_id = Column(Integer, ForeignKey('topics.id'))
    question_text = Column(String(500), nullable=True)
    user_answer = Column(String(300), nullable=True)
    correct_answer = Column(String(300), nullable=True)
    is_correct = Column(Boolean, default=False)
    attempt_number = Column(Integer, default=1)       # 1 или 2
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship('User', back_populates='attempts')
    topic = relationship('Topic', back_populates='attempts')

# ---------------------- Подключение к БД ----------------------
engine = create_engine('sqlite:///chemistry_bot.db', echo=False)
Base.metadata.create_all(engine)

SessionLocal = sessionmaker(bind=engine)
