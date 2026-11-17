import copy
import hashlib
import json
import math
import os
import re
import threading
import uuid
from datetime import date, datetime, timedelta

import flet as ft


DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

BELLS = {
    1: ("08:00", "08:45"),
    2: ("08:55", "09:40"),
    3: ("09:55", "10:40"),
    4: ("10:55", "11:40"),
    5: ("11:55", "12:40"),
    6: ("12:55", "13:40"),
    7: ("14:00", "14:45"),
}

SCHEDULE = {
    "Понедельник": [
        "Математика", "Физическая культура и здоровье", "Биология",
        "Иностранный язык", "Беларуская мова", "Беларуская літаратура",
    ],
    "Вторник": [
        "Русский язык", "Русская литература", "География",
        "Иностранный язык", "Математика", "Информатика", "Классный час",
    ],
    "Среда": [
        "Физическая культура и здоровье", "Русский язык", "История Беларуси",
        "Иностранный язык", "Математика", "Трудовое обучение", "Беларуская мова",
    ],
    "Четверг": [
        "Информационный час", "Химия", "Русская литература", "Физика",
        "Иностранный язык", "Искусство", "Математика",
    ],
    "Пятница": [
        "Всемирная история", "Математика", "Иностранный язык", "Физика",
        "Биология", "Физическая культура и здоровье",
    ],
    "Суббота": [],
}

EXCLUDED_SUBJECTS = {
    "Информационный час",
    "Классный час",
    "Физическая культура и здоровье",
    "Искусство",
}

SUBJECTS = sorted(
    {s for lessons in SCHEDULE.values() for s in lessons if s not in EXCLUDED_SUBJECTS},
    key=str.casefold,
)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

TARGET_ERROR = "Цель должна быть целым числом от 1 до 10"
GRADE_ERROR = "Введите целую оценку от 1 до 10"
DATE_ERROR = "Введите дату в формате ГГГГ-ММ-ДД"
TIME_ERROR = "Введите время в формате ЧЧ:ММ, например 08:30"
DOSE_ERROR = "Количество за приём: целое число от 1 до 20"

TRACKER_SECTIONS = ("habits", "pills", "profile", "settings", "users", "session")


def text_button(label, **kwargs):
    return ft.Button(
        content=label,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.TRANSPARENT,
            color=ft.Colors.PRIMARY,
            elevation=0,
        ),
        **kwargs,
    )


def data_path():
    folder = os.getenv("FLET_APP_STORAGE_DATA")
    if not folder:
        try:
            folder = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            folder = os.getcwd()
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "diary_data.json")


def _hash_password(password, salt=None):
    salt = salt or uuid.uuid4().hex
    digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return salt, digest


def monday_of(day):
    return day - timedelta(days=day.weekday())


def week_label(start):
    end = start + timedelta(days=5)
    if start.month == end.month:
        label = f"{start.day}–{end.day} {MONTHS[end.month - 1]}"
    else:
        label = f"{start.day} {MONTHS[start.month - 1]} – {end.day} {MONTHS[end.month - 1]}"
    return f"{label} {start.year}–{end.year}" if start.year != end.year else f"{label} {start.year}"


def valid_grade(value):
    s = str(value).strip()
    return s.isdecimal() and 1 <= int(s) <= 10


def valid_lesson_number(number):
    s = str(number)
    return s.isdecimal() and 1 <= int(s) <= 7


def lesson_subject(day, number, custom=""):
    if custom:
        return str(custom)
    template = SCHEDULE[day]
    return template[number - 1] if number <= len(template) else ""


def grades_word(count):
    if 11 <= count % 100 <= 14:
        return "оценок"
    last = count % 10
    if last == 1:
        return "оценку"
    return "оценки" if 2 <= last <= 4 else "оценок"


def parse_target(raw):
    text = str(raw or "").replace(",", ".").strip()
    try:
        value = float(text)
    except ValueError as err:
        raise ValueError(TARGET_ERROR) from err
    if not 1 <= value <= 10 or not value.is_integer():
        raise ValueError(TARGET_ERROR)
    return int(value)


def parse_time(raw):
    try:
        return datetime.strptime(str(raw or "").strip(), "%H:%M").strftime("%H:%M")
    except ValueError as err:
        raise ValueError(TIME_ERROR) from err


def parse_count(raw, low, high, error):
    try:
        value = int(str(raw or "").strip())
    except ValueError as exc:
        raise ValueError(error) from exc
    if not low <= value <= high:
        raise ValueError(error)
    return value


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _section(data, name):
    section = data.get(name)
    if not isinstance(section, dict):
        section = {}
        data[name] = section
    return section


def _set_day(data, section_name, item_id, key, day, done):
    item = _section(data, section_name).get(item_id)
    if not isinstance(item, dict):
        return
    days = item.get(key)
    if not isinstance(days, list):
        days = []
        item[key] = days
    if done and day not in days:
        days.append(day)
    elif not done and day in days:
        days.remove(day)
    days.sort()


def streak(days_set, today):
    current = today if today.isoformat() in days_set else today - timedelta(days=1)
    count = 0
    while current.isoformat() in days_set:
        count += 1
        current -= timedelta(days=1)
    return count


class Store:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.data = {"weeks": {}}
        try:
            with open(path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
            if isinstance(loaded, dict) and isinstance(loaded.get("weeks"), dict):
                self.data = {"weeks": loaded["weeks"]}
                for key in TRACKER_SECTIONS:
                    if isinstance(loaded.get(key), dict):
                        self.data[key] = loaded[key]
            else:
                self._backup_corrupt()
                self.save()
        except FileNotFoundError:
            self.save()
        except (OSError, ValueError):
            self._backup_corrupt()
            self.data = {"weeks": {}}
            self.save()
        if self._migrate_legacy():
            self.save()

    def _backup_corrupt(self):
        try:
            if os.path.exists(self.path):
                os.replace(self.path, self.path + ".corrupt")
        except OSError:
            pass

    def _migrate_legacy(self):
        changed = False
        for week, week_data in self.data.get("weeks", {}).items():
            if not isinstance(week_data, dict):
                continue
            try:
                monday = date.fromisoformat(week)
            except (TypeError, ValueError):
                monday = date.today()
            for day_name, day_data in week_data.items():
                if not isinstance(day_data, dict):
                    continue
                day_offset = DAYS.index(day_name) if day_name in DAYS else 0
                for cell in day_data.values():
                    if not isinstance(cell, dict):
                        continue
                    if "grade" in cell:
                        old_grade = cell.pop("grade")
                        changed = True
                        if valid_grade(old_grade) and not cell.get("grades"):
                            cell["grades"] = [{
                                "id": uuid.uuid4().hex,
                                "date": (monday + timedelta(days=day_offset)).isoformat(),
                                "value": int(str(old_grade).strip()),
                                "reason": "Перенесено из предыдущей версии",
                            }]
                    if "grades" not in cell:
                        cell["grades"] = []
                        changed = True
                    if isinstance(cell["grades"], list):
                        for item in cell["grades"]:
                            if isinstance(item, dict) and not item.get("id"):
                                item["id"] = uuid.uuid4().hex
                                changed = True
        return changed

    def save(self):
        with self.lock:
            temporary = self.path + ".tmp"
            try:
                with open(temporary, "w", encoding="utf-8") as file:
                    json.dump(self.data, file, ensure_ascii=False, indent=2)
                os.replace(temporary, self.path)
            except OSError as error:
                try:
                    if os.path.exists(temporary):
                        os.remove(temporary)
                except OSError:
                    pass
                raise RuntimeError(f"Не удалось сохранить дневник: {error}") from error

    def _mutate(self, change):
        with self.lock:
            snapshot = copy.deepcopy(self.data)
            try:
                result = change(self.data)
                self.save()
                return result
            except Exception:
                self.data = snapshot
                raise

    # --- БЛОК АВТОРИЗАЦИИ И СЕССИЙ ---

    @staticmethod
    def _normalize_email(email):
        return str(email or "").strip().lower()

    def register_user(self, email, password, name=""):
        clean_email = self._normalize_email(email)
        raw_pass = str(password or "")
        if not EMAIL_REGEX.match(clean_email):
            raise ValueError("Введите корректный email")
        if len(raw_pass) < 6:
            raise ValueError("Пароль должен содержать не менее 6 символов")

        def change(data):
            users = _section(data, "users")
            if clean_email in users:
                raise ValueError("Пользователь с таким email уже существует")
            salt, password_hash = _hash_password(raw_pass)
            users[clean_email] = {
                "salt": salt,
                "password_hash": password_hash,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            if str(name or "").strip():
                _section(data, "profile")["name"] = str(name).strip()[:30]
            _section(data, "session")["email"] = clean_email

        self._mutate(change)
        return clean_email

    def login_user(self, email, password):
        clean_email = self._normalize_email(email)
        raw_pass = str(password or "")
        if not EMAIL_REGEX.match(clean_email):
            raise ValueError("Введите корректный email")
        if not raw_pass:
            raise ValueError("Введите пароль")

        def change(data):
            users = _section(data, "users")
            user = users.get(clean_email)
            if not isinstance(user, dict):
                raise ValueError("Пользователь с таким email не найден")
            _, candidate_hash = _hash_password(raw_pass, user.get("salt", ""))
            if candidate_hash != user.get("password_hash"):
                raise ValueError("Неверный пароль")
            _section(data, "session")["email"] = clean_email

        self._mutate(change)
        return clean_email

    def get_current_user(self):
        with self.lock:
            session = self.data.get("session")
            if not isinstance(session, dict):
                return None
            email = self._normalize_email(session.get("email"))
            users = self.data.get("users")
            if email and isinstance(users, dict) and isinstance(users.get(email), dict):
                return email
            return None

    def logout_user(self):
        self._mutate(lambda d: d.pop("session", None))

    # --- ОСНОВНЫЕ ДАННЫЕ ДНЕВНИКА ---

    def _day_data(self, week, day):
        week_data = self.data["weeks"].get(week)
        if not isinstance(week_data, dict):
            return {}
        day_data = week_data.get(day)
        return day_data if isinstance(day_data, dict) else {}

    def _cell(self, week, day, number):
        value = self._day_data(week, day).get(str(number), {})
        if not isinstance(value, dict):
            value = {}
        grades = value.get("grades", [])
        safe_grades = [
            {
                "id": str(item.get("id") or uuid.uuid4().hex),
                "date": str(item.get("date") or week),
                "value": int(str(item["value"]).strip()),
                "reason": str(item.get("reason") or ""),
            }
            for item in (grades if isinstance(grades, list) else [])
            if isinstance(item, dict) and valid_grade(item.get("value", ""))
        ]
        return {
            "hw": str(value.get("hw") or ""),
            "subject": str(value.get("subject") or ""),
            "grades": safe_grades,
        }

    def get(self, week, day, number):
        with self.lock:
            return self._cell(week, day, number)

    def lesson_numbers(self, week, day):
        with self.lock:
            numbers = set(range(1, len(SCHEDULE[day]) + 1))
            numbers.update(int(k) for k in self._day_data(week, day) if valid_lesson_number(k))
            return sorted(numbers)

    def _cleanup(self, week, day):
        week_data = self.data["weeks"].get(week, {})
        day_data = week_data.get(day, {})
        for key in list(day_data):
            if valid_lesson_number(key):
                cell = self._cell(week, day, int(key))
                if not cell["hw"].strip() and not cell["subject"] and not cell["grades"]:
                    del day_data[key]
        if not day_data:
            week_data.pop(day, None)
        if not week_data:
            self.data["weeks"].pop(week, None)

    def _store_cell(self, week, day, number, cell):
        day_data = self.data["weeks"].setdefault(week, {}).setdefault(day, {})
        if cell["hw"].strip() or cell["subject"] or cell["grades"]:
            day_data[str(number)] = cell
        else:
            day_data.pop(str(number), None)
        self._cleanup(week, day)

    def _update(self, week, day, number, change):
        def apply(data):
            cell = self._cell(week, day, number)
            change(cell)
            self._store_cell(week, day, number, cell)
        self._mutate(apply)

    def set_homework(self, week, day, number, homework):
        self._update(week, day, number, lambda c: c.update({"hw": str(homework or "").strip()}))

    def set_subject(self, week, day, number, subject):
        self._update(week, day, number, lambda c: c.update({"subject": str(subject or "").strip()}))

    def add_grade(self, week, day, number, grade, grade_date, reason, grade_id=None):
        if not valid_grade(grade):
            raise ValueError(GRADE_ERROR)
        try:
            date.fromisoformat(str(grade_date))
        except ValueError as error:
            raise ValueError(DATE_ERROR) from error
        record = {
            "id": grade_id or uuid.uuid4().hex,
            "date": str(grade_date),
            "value": int(str(grade).strip()),
            "reason": str(reason or "").strip(),
        }

        def change(cell):
            cell["grades"] = [i for i in cell["grades"] if i["id"] != record["id"]] + [record]
            cell["grades"].sort(key=lambda i: i["date"])

        self._update(week, day, number, change)

    def delete_grade(self, week, day, number, grade_id):
        self._update(week, day, number, lambda c: c.update(
            {"grades": [i for i in c["grades"] if i["id"] != grade_id]}
        ))

    def all_subjects(self):
        with self.lock:
            names = set(SUBJECTS)
            for week_data in self.data["weeks"].values():
                if isinstance(week_data, dict):
                    for day_data in week_data.values():
                        if isinstance(day_data, dict):
                            for raw in day_data.values():
                                if isinstance(raw, dict) and raw.get("subject"):
                                    subj = str(raw["subject"])
                                    if subj not in EXCLUDED_SUBJECTS:
                                        names.add(subj)
            return sorted(names, key=str.casefold)

    def count_homework(self):
        with self.lock:
            return sum(
                1
                for week_data in self.data["weeks"].values() if isinstance(week_data, dict)
                for day_data in week_data.values() if isinstance(day_data, dict)
                for raw in day_data.values()
                if isinstance(raw, dict) and str(raw.get("hw") or "").strip()
            )

    def grades_by_subject(self):
        result = {}
        with self.lock:
            for week, week_data in self.data["weeks"].items():
                if not isinstance(week_data, dict):
                    continue
                try:
                    week_start = date.fromisoformat(week)
                except (TypeError, ValueError):
                    continue
                for day_index, day in enumerate(DAYS):
                    day_data = week_data.get(day, {})
                    if not isinstance(day_data, dict):
                        continue
                    for number, raw in day_data.items():
                        if not valid_lesson_number(number) or not isinstance(raw, dict):
                            continue
                        lesson = int(number)
                        grades = raw.get("grades", [])
                        if not isinstance(grades, list):
                            continue
                        subject = lesson_subject(day, lesson, str(raw.get("subject") or ""))
                        for item in grades:
                            if isinstance(item, dict) and valid_grade(item.get("value", "")):
                                result.setdefault(subject, []).append({
                                    "id": str(item.get("id") or ""),
                                    "date": str(item.get("date") or (week_start + timedelta(days=day_index)).isoformat()),
                                    "value": int(str(item["value"]).strip()),
                                    "reason": str(item.get("reason") or ""),
                                    "week": week,
                                    "day": day,
                                    "number": lesson,
                                })
        for records in result.values():
            records.sort(key=lambda i: (i["date"], i["number"]))
        return result

    def subject_grades(self, subject):
        return self.grades_by_subject().get(subject, [])

    def theme(self):
        with self.lock:
            settings = self.data.get("settings")
            return "light" if isinstance(settings, dict) and settings.get("theme") == "light" else "dark"

    def set_theme(self, value):
        if value not in ("light", "dark"):
            raise ValueError("Неизвестная тема")
        self._mutate(lambda d: _section(d, "settings").update({"theme": value}))

    def habits(self):
        with self.lock:
            section = self.data.get("habits")
            if not isinstance(section, dict):
                return []
            result = [
                {
                    "id": str(hid),
                    "name": str(raw.get("name") or ""),
                    "done": {str(day) for day in (raw.get("done") if isinstance(raw.get("done"), list) else [])},
                }
                for hid, raw in section.items() if isinstance(raw, dict)
            ]
            return sorted(result, key=lambda i: i["name"].casefold())

    def add_habit(self, name):
        text = str(name or "").strip()
        if not text:
            raise ValueError("Введите название привычки")
        self._mutate(lambda d: _section(d, "habits").update({uuid.uuid4().hex: {"name": text[:40], "done": []}}))

    def rename_habit(self, habit_id, name):
        text = str(name or "").strip()
        if not text:
            raise ValueError("Введите название привычки")

        def change(data):
            item = _section(data, "habits").get(habit_id)
            if not isinstance(item, dict):
                raise ValueError("Привычка не найдена")
            item["name"] = text[:40]

        self._mutate(change)

    def set_habit_done(self, habit_id, day, done):
        self._mutate(lambda d: _set_day(d, "habits", habit_id, "done", day, done))

    def delete_habit(self, habit_id):
        self._mutate(lambda d: _section(d, "habits").pop(habit_id, None))

    def pills(self):
        with self.lock:
            section = self.data.get("pills")
            if not isinstance(section, dict):
                return []
            result = []
            for pid, raw in section.items():
                if not isinstance(raw, dict):
                    continue
                taken = raw.get("taken") if isinstance(raw.get("taken"), list) else []
                try:
                    time_text = parse_time(raw.get("time"))
                except ValueError:
                    time_text = "00:00"
                result.append({
                    "id": str(pid),
                    "name": str(raw.get("name") or ""),
                    "time": time_text,
                    "dose": max(1, _as_int(raw.get("dose"), 1)),
                    "note": str(raw.get("note") or ""),
                    "taken": {str(day) for day in taken},
                })
            return sorted(result, key=lambda i: (i["time"], i["name"].casefold()))

    @staticmethod
    def _pill_values(name, time_text, dose, note):
        text = str(name or "").strip()
        if not text:
            raise ValueError("Введите название лекарства")
        return {
            "name": text[:40],
            "time": parse_time(time_text),
            "dose": parse_count(dose, 1, 20, DOSE_ERROR),
            "note": str(note or "").strip()[:60],
        }

    def add_pill(self, name, time_text, dose, note):
        values = self._pill_values(name, time_text, dose, note)
        self._mutate(lambda d: _section(d, "pills").update({uuid.uuid4().hex: {**values, "taken": []}}))

    def update_pill(self, pill_id, name, time_text, dose, note):
        values = self._pill_values(name, time_text, dose, note)

        def change(data):
            item = _section(data, "pills").get(pill_id)
            if not isinstance(item, dict):
                raise ValueError("Лекарство не найдено")
            item.update(values)

        self._mutate(change)

    def set_pill_taken(self, pill_id, day, taken):
        self._mutate(lambda d: _set_day(d, "pills", pill_id, "taken", day, taken))

    def delete_pill(self, pill_id):
        self._mutate(lambda d: _section(d, "pills").pop(pill_id, None))

    def tracker_stats(self, today):
        return {
            "habit_streak": max((streak(i["done"], today) for i in self.habits()), default=0),
            "pill_days": max((len(i["taken"]) for i in self.pills()), default=0),
        }

    def get_name(self):
        with self.lock:
            profile = self.data.get("profile")
            return str(profile.get("name") or "") if isinstance(profile, dict) else ""

    def set_name(self, name):
        self._mutate(lambda d: _section(d, "profile").update({"name": str(name or "").strip()[:30]}))


def target_threshold(target):
    return max(1.0, target - 0.5)


def target_plan(grades, target):
    threshold = target_threshold(target)
    current_sum = sum(grades)
    current_count = len(grades)
    for future_count in range(1, 101):
        required = max(future_count, math.ceil(threshold * (current_count + future_count) - current_sum - 1e-9))
        if required <= 10 * future_count:
            low, extra = divmod(required, future_count)
            return [low] * (future_count - extra) + [low + 1] * extra
    return None


ACHIEVEMENTS = [
    {"title": "Первая оценка", "text": "Получена первая оценка", "icon": ft.Icons.BOLT, "check": lambda s: s["grades"] >= 1},
    {"title": "Пять оценок", "text": "Накоплено 5 оценок", "icon": ft.Icons.FILTER_5, "check": lambda s: s["grades"] >= 5},
    {"title": "Двадцатка", "text": "Накоплено 20 оценок", "icon": ft.Icons.WORKSPACE_PREMIUM, "check": lambda s: s["grades"] >= 20},
    {"title": "Отличник", "text": "Средний балл от 9 при 5+ оценках", "icon": ft.Icons.AUTO_AWESOME, "check": lambda s: s["grades"] >= 5 and s["average"] >= 9},
    {"title": "Внимательный", "text": "Записано 10 домашних заданий", "icon": ft.Icons.TERMINAL, "check": lambda s: s["homework"] >= 10},
    {"title": "Всё под контролем", "text": "Оценки по 5 предметам", "icon": ft.Icons.HUB, "check": lambda s: s["subjects"] >= 5},
    {"title": "Серия привычек", "text": "Привычка 7 дней подряд", "icon": ft.Icons.LOCAL_FIRE_DEPARTMENT, "check": lambda s: s["habit_streak"] >= 7},
    {"title": "Без пропусков", "text": "Таблетки приняты 7 дней", "icon": ft.Icons.SHIELD, "check": lambda s: s["pill_days"] >= 7},
]


def home_stats(store, today):
    by_subject = store.grades_by_subject()
    values = [item["value"] for records in by_subject.values() for item in records]
    stats = {
        "grades": len(values),
        "average": sum(values) / len(values) if values else 0.0,
        "subjects": len(by_subject),
        "homework": store.count_homework(),
    }
    stats.update(store.tracker_stats(today))
    return stats


def unlocked_achievements(stats):
    return [item for item in ACHIEVEMENTS if item["check"](stats)]


def grade_color(val):
    if val >= 9:
        return ft.Colors.TEAL_400
    if val >= 7:
        return ft.Colors.CYAN_400
    if val >= 5:
        return ft.Colors.AMBER_400
    return ft.Colors.ERROR


def greeting(hour):
    if 5 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    return "Добрый вечер" if 18 <= hour < 23 else "Доброй ночи"


class AuthView:
    def __init__(self, page: ft.Page, store: Store, on_success):
        self.page = page
        self.store = store
        self.on_success = on_success
        self.is_register = False

        self.title_text = ft.Text("Вход в NEXUS", size=22, weight=ft.FontWeight.BOLD)
        self.subtitle_text = ft.Text(
            "Войди в свой аккаунт, чтобы открыть дневник",
            size=13,
            color=ft.Colors.OUTLINE,
        )
        self.name_field = ft.TextField(
            label="Имя (необязательно)",
            max_length=30,
            visible=False,
        )
        self.email_field = ft.TextField(
            label="Email",
            hint_text="student@example.com",
            autofocus=True,
            on_submit=self.handle_submit,
        )
        self.password_field = ft.TextField(
            label="Пароль",
            password=True,
            can_reveal_password=True,
            on_submit=self.handle_submit,
        )
        self.error_text = ft.Text(
            "",
            color=ft.Colors.ERROR,
            size=13,
            visible=False,
        )
        self.submit_btn = ft.Button(
            content="Войти",
            expand=True,
            on_click=self.handle_submit,
        )
        self.toggle_btn = text_button(
            "Нет аккаунта? Зарегистрироваться",
            on_click=self.toggle_mode,
        )

    def _is_desktop(self):
        return (self.page.width or 800) >= 700

    def toggle_mode(self, event=None):
        self.is_register = not self.is_register
        self.error_text.value = ""
        self.error_text.visible = False
        if self.is_register:
            self.title_text.value = "Регистрация в NEXUS"
            self.subtitle_text.value = "Создай профиль для синхронизации оценок и привычек"
            self.name_field.visible = True
            self.password_field.label = "Пароль (от 6 символов)"
            self.submit_btn.content = "Создать аккаунт"
            self.toggle_btn.content = "Уже есть аккаунт? Войти"
        else:
            self.title_text.value = "Вход в NEXUS"
            self.subtitle_text.value = "Войди в свой аккаунт, чтобы открыть дневник"
            self.name_field.visible = False
            self.password_field.label = "Пароль"
            self.submit_btn.content = "Войти"
            self.toggle_btn.content = "Нет аккаунта? Зарегистрироваться"
        self.page.update()

    def handle_submit(self, event=None):
        self.error_text.value = ""
        self.error_text.visible = False

        email = (self.email_field.value or "").strip()
        password = self.password_field.value or ""

        try:
            if not EMAIL_REGEX.match(email.lower()):
                raise ValueError("Введите корректный email")
            if self.is_register:
                if len(password) < 6:
                    raise ValueError("Пароль должен быть не менее 6 символов")
                self.store.register_user(email, password, name=self.name_field.value or "")
            else:
                if not password:
                    raise ValueError("Введите пароль")
                self.store.login_user(email, password)
        except ValueError as err:
            self.error_text.value = str(err)
            self.error_text.visible = True
            self.page.update()
            return
        except Exception as err:
            self.error_text.value = f"Ошибка сохранения: {err}"
            self.error_text.visible = True
            self.page.update()
            return

        self.on_success()

    def build(self):
        desktop = self._is_desktop()
        card_padding = 26 if desktop else 14
        outer_padding = 24 if desktop else 12

        card = ft.Container(
            padding=card_padding,
            border_radius=18,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border=ft.Border.all(1, ft.Colors.with_opacity(0.14, ft.Colors.OUTLINE)),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Container(
                                width=46,
                                height=46,
                                border_radius=14,
                                bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY),
                                border=ft.Border.all(1.5, ft.Colors.PRIMARY),
                                alignment=ft.Alignment(0, 0),
                                content=ft.Icon(ft.Icons.SHIELD, color=ft.Colors.PRIMARY, size=24),
                            ),
                            ft.Column([self.title_text, self.subtitle_text], spacing=2, expand=True),
                        ],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.name_field,
                    self.email_field,
                    self.password_field,
                    self.error_text,
                    ft.Row([self.submit_btn]),
                    ft.Row([self.toggle_btn], alignment=ft.MainAxisAlignment.CENTER, wrap=True),
                ],
                spacing=14,
                tight=True,
            ),
        )

        responsive_wrapper = ft.ResponsiveRow(
            [
                ft.Container(col={"xs": 0, "sm": 2, "md": 3, "lg": 4}),
                ft.Column(col={"xs": 12, "sm": 8, "md": 6, "lg": 4}, controls=[card]),
                ft.Container(col={"xs": 0, "sm": 2, "md": 3, "lg": 4}),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        )

        return ft.Container(
            expand=True,
            padding=outer_padding,
            alignment=ft.Alignment(0, 0),
            content=ft.Column(
                [responsive_wrapper],
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )


class DiaryApp:
    def __init__(self, page: ft.Page, store: Store = None, on_logout=None):
        self.page = page
        self.store = store or Store(data_path())
        self.on_logout = on_logout
        self.week = monday_of(date.today())
        self.selected_day_idx = min(date.today().weekday(), 5)
        self.main_tab = 0
        self.school_tab = "schedule"
        self.selected_subject = None
        self.day_pill_refs = []
        self.day_card_heights = []
        self.schedule_list = None
        self.programmatic_scroll = False
        self._last_is_tablet = self.is_tablet()

        page.title = "NEXUS // Дневник"
        page.padding = 0
        page.theme = ft.Theme(color_scheme_seed=ft.Colors.CYAN)
        self.apply_theme()

        self.body = ft.Container(expand=True, padding=self._adaptive_page_padding())
        self.nav = ft.NavigationBar(
            selected_index=0,
            height=64,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.SPACE_DASHBOARD_OUTLINED, selected_icon=ft.Icons.SPACE_DASHBOARD, label="Дашборд"),
                ft.NavigationBarDestination(icon=ft.Icons.SCHOOL_OUTLINED, selected_icon=ft.Icons.SCHOOL, label="Учёба"),
                ft.NavigationBarDestination(icon=ft.Icons.TUNE_OUTLINED, selected_icon=ft.Icons.TUNE, label="Система"),
            ],
            on_change=self.on_main_nav,
        )
        page.on_resized = self._on_viewport_resize
        page.controls.clear()
        page.add(self.body)
        page.navigation_bar = self.nav
        self.render()

    def is_tablet(self):
        return (self.page.width or 800) >= 700

    def _adaptive_page_padding(self):
        if self.is_tablet():
            return ft.Padding(24, 18, 24, 12)
        return ft.Padding(12, 10, 12, 8)

    def _on_viewport_resize(self, event=None):
        current_tablet = self.is_tablet()
        if current_tablet != self._last_is_tablet:
            self._last_is_tablet = current_tablet
            self.body.padding = self._adaptive_page_padding()
            self.render()

    def apply_theme(self):
        dark = self.store.theme() == "dark"
        self.page.theme_mode = ft.ThemeMode.DARK if dark else ft.ThemeMode.LIGHT
        self.page.bgcolor = ft.Colors.SURFACE

    def snack(self, message):
        self.page.show_dialog(ft.SnackBar(content=ft.Text(message), behavior=ft.SnackBarBehavior.FLOATING))

    def on_main_nav(self, event):
        self.main_tab = event.control.selected_index
        self.selected_subject = None
        self.render()

    def render(self):
        self.body.padding = self._adaptive_page_padding()
        if self.main_tab == 0:
            self.render_home()
        elif self.main_tab == 1:
            self.render_school()
        else:
            self.render_settings()

    def open_dialog(self, title, content, actions):
        self.page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD),
            content=content,
            actions=actions,
            actions_alignment=ft.MainAxisAlignment.END,
        ))

    def run_action(self, action, dialog=False):
        try:
            action()
        except Exception as error:
            self.snack(str(error))
            return
        if dialog:
            self.page.pop_dialog()
        self.render()

    def card_box(self, content, padding=None, border_color=None):
        if padding is None:
            padding = 20 if self.is_tablet() else 14
        return ft.Container(
            padding=padding,
            border_radius=16,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            border=ft.Border.all(1, border_color or ft.Colors.with_opacity(0.12, ft.Colors.OUTLINE)),
            content=content,
        )

    def render_home(self):
        stats = home_stats(self.store, date.today())
        tablet = self.is_tablet()
        gap = 16 if tablet else 12

        trackers_block = (
            ft.ResponsiveRow(
                [
                    ft.Column(col={"xs": 12, "md": 6}, controls=[self.habits_card()]),
                    ft.Column(col={"xs": 12, "md": 6}, controls=[self.pills_card()]),
                ],
                spacing=gap,
                run_spacing=gap,
            )
            if tablet
            else ft.Column([self.habits_card(), self.pills_card()], spacing=gap)
        )

        content_layout = [
            self.home_header(stats),
            self.kpi_row(stats),
            trackers_block,
            self.achievements_view(stats),
        ]

        self.body.content = ft.Column(
            content_layout,
            spacing=gap,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.update()

    def today_lessons_count(self):
        today = date.today()
        if today.weekday() >= 6:
            return 0
        day = DAYS[today.weekday()]
        week_key = monday_of(today).isoformat()
        return sum(
            1 for n in self.store.lesson_numbers(week_key, day)
            if lesson_subject(day, n, self.store.get(week_key, day, n)["subject"])
        )

    def home_header(self, stats):
        tablet = self.is_tablet()
        name = self.store.get_name() or "Студент"
        unlocked = len(unlocked_achievements(stats))
        level = 1 + unlocked // 3
        progress = (unlocked % 3) / 3
        initial = name[0].upper()

        avatar_size = 60 if tablet else 48
        title_size = 22 if tablet else 18
        header_padding = 22 if tablet else 14

        return self.card_box(
            ft.Row(
                [
                    ft.Container(
                        width=avatar_size,
                        height=avatar_size,
                        border_radius=16 if tablet else 14,
                        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY),
                        border=ft.Border.all(1.5, ft.Colors.PRIMARY),
                        alignment=ft.Alignment(0, 0),
                        content=ft.Text(
                            initial,
                            size=26 if tablet else 21,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.PRIMARY,
                        ),
                    ),
                    ft.Column(
                        [
                            ft.Text(
                                f"{greeting(datetime.now().hour)}, {name}",
                                size=title_size,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Row(
                                [
                                    ft.Container(
                                        padding=ft.Padding(10, 3, 10, 3),
                                        border_radius=8,
                                        bgcolor=ft.Colors.PRIMARY,
                                        content=ft.Text(
                                            f"LVL {level}",
                                            size=12,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.ON_PRIMARY,
                                        ),
                                    ),
                                    ft.Container(
                                        expand=True,
                                        content=ft.ProgressBar(value=progress, height=8, border_radius=4),
                                    ),
                                ],
                                spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=8,
                        expand=True,
                    ),
                ],
                spacing=16 if tablet else 12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=header_padding,
        )

    def kpi_row(self, stats):
        tablet = self.is_tablet()
        avg_str = f"{stats['average']:.2f}" if stats["grades"] else "—"
        lessons = self.today_lessons_count()
        lessons_str = str(lessons) if lessons else "Выходной"

        def metric(icon, label, value, accent=ft.Colors.PRIMARY):
            if tablet:
                return ft.Container(
                    expand=True,
                    padding=18,
                    border_radius=14,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.OUTLINE)),
                    content=ft.Column(
                        [
                            ft.Row(
                                [ft.Icon(icon, size=18, color=accent), ft.Text(label, size=12, color=ft.Colors.OUTLINE)],
                                spacing=6,
                            ),
                            ft.Text(value, size=24, weight=ft.FontWeight.BOLD, color=accent),
                        ],
                        spacing=6,
                    ),
                )
            return ft.Container(
                padding=14,
                border_radius=14,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                border=ft.Border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.OUTLINE)),
                content=ft.Row(
                    [
                        ft.Icon(icon, size=20, color=accent),
                        ft.Text(label, size=14, color=ft.Colors.OUTLINE, expand=True),
                        ft.Text(value, size=20, weight=ft.FontWeight.BOLD, color=accent),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )

        items = [
            metric(ft.Icons.INSIGHTS, "Ср. балл", avg_str, grade_color(stats["average"]) if stats["grades"] else ft.Colors.PRIMARY),
            metric(ft.Icons.TODAY, "Уроков сегодня", lessons_str),
            metric(ft.Icons.ASSIGNMENT_TURNED_IN, "Д/З", str(stats["homework"])),
        ]

        if tablet:
            return ft.Row(items, spacing=14)
        return ft.Column(items, spacing=10)

    def tracker_frame(self, icon, title, subtitle, body_controls, trailing=None):
        header_items = [
            ft.Icon(icon, color=ft.Colors.PRIMARY, size=22),
            ft.Column(
                [
                    ft.Text(title, size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(subtitle, size=12, color=ft.Colors.OUTLINE),
                ],
                spacing=2,
                expand=True,
            ),
        ]
        if trailing:
            header_items.append(trailing)
        return self.card_box(
            ft.Column(
                [
                    ft.Row(header_items, spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    *body_controls,
                ],
                spacing=12,
            )
        )

    def habit_toggled(self, habit_id, done):
        self.run_action(lambda: self.store.set_habit_done(habit_id, date.today().isoformat(), done))

    def habits_card(self):
        today = date.today()
        habits = self.store.habits()
        rows = [
            ft.Row(
                [
                    ft.Checkbox(
                        label=h["name"],
                        value=today.isoformat() in h["done"],
                        on_change=lambda e, hid=h["id"]: self.habit_toggled(hid, e.control.value),
                        expand=True,
                    ),
                    ft.Container(
                        padding=ft.Padding(10, 4, 10, 4),
                        border_radius=8,
                        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY) if streak(h["done"], today) else ft.Colors.TRANSPARENT,
                        content=ft.Text(
                            f"🔥 {streak(h['done'], today)} дн.",
                            size=13,
                            weight=ft.FontWeight.W_600,
                            color=ft.Colors.PRIMARY if streak(h["done"], today) else ft.Colors.OUTLINE,
                        ),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            for h in habits
        ] or [ft.Text("Нет активных привычек — добавь в разделе «Система»", size=13, color=ft.Colors.OUTLINE)]
        return self.tracker_frame(ft.Icons.LOCAL_FIRE_DEPARTMENT, "Трекер привычек", "Ежедневный чек-ин", rows)

    def pill_toggled(self, pill_id, taken):
        self.run_action(lambda: self.store.set_pill_taken(pill_id, date.today().isoformat(), taken))

    def pills_card(self):
        today = date.today().isoformat()
        pills = self.store.pills()
        rows = []
        for p in pills:
            label_text = f"{p['time']} · {p['name']} ({p['dose']} шт.)"
            if p["note"]:
                label_text += f" — {p['note']}"
            rows.append(
                ft.Checkbox(
                    label=label_text,
                    value=today in p["taken"],
                    on_change=lambda e, pid=p["id"]: self.pill_toggled(pid, e.control.value),
                )
            )
        if not rows:
            rows.append(ft.Text("Список пуст — настрой расписание в «Системе»", size=13, color=ft.Colors.OUTLINE))
        return self.tracker_frame(ft.Icons.MEDICATION, "Витамины и приём", "Контроль графика", rows)

    def achievements_view(self, stats):
        tablet = self.is_tablet()
        unlocked = {item["title"] for item in unlocked_achievements(stats)}
        tiles = []
        for item in ACHIEVEMENTS:
            done = item["title"] in unlocked
            card = ft.Container(
                padding=16 if tablet else 12,
                border_radius=14,
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY) if done else ft.Colors.SURFACE_CONTAINER_LOW,
                border=ft.Border.all(
                    1,
                    ft.Colors.PRIMARY if done else ft.Colors.with_opacity(0.1, ft.Colors.OUTLINE),
                ),
                opacity=1.0 if done else 0.45,
                content=ft.Column(
                    [
                        ft.Icon(item["icon"], size=24, color=ft.Colors.PRIMARY if done else ft.Colors.OUTLINE),
                        ft.Text(item["title"], weight=ft.FontWeight.BOLD, size=14),
                        ft.Text(item["text"], size=12, color=ft.Colors.OUTLINE),
                    ],
                    spacing=6,
                ),
            )
            tiles.append(ft.Column(col={"xs": 6, "sm": 4, "md": 3}, controls=[card]))

        return ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Достижения", size=18, weight=ft.FontWeight.BOLD, expand=True),
                        ft.Text(f"{len(unlocked)} / {len(ACHIEVEMENTS)}", size=14, color=ft.Colors.PRIMARY, weight=ft.FontWeight.BOLD),
                    ]
                ),
                ft.ResponsiveRow(tiles, spacing=12 if tablet else 10, run_spacing=12 if tablet else 10),
            ],
            spacing=12,
        )

    def theme_changed(self, value):
        def action():
            self.store.set_theme("dark" if value else "light")
            self.apply_theme()
        self.run_action(action)

    def handle_logout(self, event=None):
        self.store.logout_user()
        if self.on_logout is not None:
            self.on_logout()

    def render_settings(self):
        name = self.store.get_name()
        current_email = self.store.get_current_user() or "Не авторизован"
        habits = self.store.habits()
        pills = self.store.pills()

        account_card = self.tracker_frame(
            ft.Icons.SHIELD,
            "Аккаунт",
            "Текущая активная сессия",
            [ft.Row(
                [
                    ft.Text(current_email, size=15, expand=True, weight=ft.FontWeight.W_600),
                    text_button("Выйти", on_click=self.handle_logout),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )],
        )

        profile_card = self.tracker_frame(
            ft.Icons.BADGE_OUTLINED,
            "Профиль",
            "Отображаемое имя",
            [ft.Row(
                [
                    ft.Text(name or "Не указано", size=15, expand=True, color=None if name else ft.Colors.OUTLINE),
                    ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_size=20, on_click=lambda e: self.open_name_dialog()),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )],
        )

        theme_card = self.tracker_frame(
            ft.Icons.CONTRAST,
            "Интерфейс",
            "Цветовая схема",
            [ft.Row(
                [
                    ft.Text("Тёмный режим", size=15, expand=True),
                    ft.Switch(value=self.store.theme() == "dark", on_change=lambda e: self.theme_changed(e.control.value)),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )],
        )

        habit_rows = [
            ft.Row(
                [
                    ft.Text(h["name"], size=15, expand=True),
                    ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_size=20, on_click=lambda e, item=h: self.open_habit_dialog(item)),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_size=20,
                        on_click=lambda e, item=h: self.confirm_delete(
                            f"Удалить «{item['name']}»?",
                            "История отметок будет удалена.",
                            lambda hid=item["id"]: self.store.delete_habit(hid),
                        ),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
            for h in habits
        ] or [ft.Text("Список пуст", size=13, color=ft.Colors.OUTLINE)]

        habits_card = self.tracker_frame(
            ft.Icons.LOCAL_FIRE_DEPARTMENT,
            "Привычки",
            "Управление целями",
            habit_rows,
            trailing=ft.IconButton(icon=ft.Icons.ADD_CIRCLE_OUTLINE, on_click=lambda e: self.open_habit_dialog(None)),
        )

        pill_rows = []
        for p in pills:
            sub = f"{p['time']} · {p['name']} ({p['dose']} шт.)"
            if p["note"]:
                sub += f" · {p['note']}"
            pill_rows.append(
                ft.Row(
                    [
                        ft.Text(sub, size=14, expand=True),
                        ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_size=20, on_click=lambda e, item=p: self.open_pill_dialog(item)),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            icon_size=20,
                            on_click=lambda e, item=p: self.confirm_delete(
                                f"Удалить «{item['name']}»?",
                                "История приёма будет удалена.",
                                lambda pid=item["id"]: self.store.delete_pill(pid),
                            ),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        if not pill_rows:
            pill_rows.append(ft.Text("Список пуст", size=13, color=ft.Colors.OUTLINE))

        pills_card = self.tracker_frame(
            ft.Icons.MEDICATION,
            "Таблетки и витамины",
            "График приёма и заметки",
            pill_rows,
            trailing=ft.IconButton(icon=ft.Icons.ADD_CIRCLE_OUTLINE, on_click=lambda e: self.open_pill_dialog(None)),
        )

        self.body.content = ft.Column(
            [
                ft.Text("Система", size=26, weight=ft.FontWeight.BOLD),
                account_card,
                profile_card,
                theme_card,
                habits_card,
                pills_card,
            ],
            spacing=16,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.update()

    def open_name_dialog(self):
        field = ft.TextField(label="Имя", value=self.store.get_name(), max_length=30, autofocus=True)
        self.open_dialog(
            "Твоё имя",
            ft.Container(width=340, content=field),
            [
                text_button("Отмена", on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content="Сохранить", on_click=lambda e: self.run_action(lambda: self.store.set_name(field.value), dialog=True)),
            ],
        )

    def open_habit_dialog(self, habit=None):
        field = ft.TextField(label="Название", value=habit["name"] if habit else "", max_length=40, autofocus=True)
        self.open_dialog(
            "Новая привычка" if habit is None else "Изменить привычку",
            ft.Container(width=340, content=field),
            [
                text_button("Отмена", on_click=lambda e: self.page.pop_dialog()),
                ft.Button(
                    content="Сохранить",
                    on_click=lambda e: self.run_action(
                        lambda: self.store.add_habit(field.value) if habit is None else self.store.rename_habit(habit["id"], field.value),
                        dialog=True,
                    ),
                ),
            ],
        )

    def open_pill_dialog(self, pill=None):
        name_f = ft.TextField(label="Название", max_length=40, autofocus=True, value=pill["name"] if pill else "")
        time_f = ft.TextField(label="Время", hint_text="ЧЧ:ММ", width=140, value=pill["time"] if pill else "08:00")
        dose_f = ft.TextField(label="За приём", width=150, keyboard_type=ft.KeyboardType.NUMBER, value=str(pill["dose"]) if pill else "1")
        note_f = ft.TextField(label="Заметка (например, после еды)", max_length=60, value=pill["note"] if pill else "")

        self.open_dialog(
            "Добавить препарат" if pill is None else "Изменить препарат",
            ft.Container(
                width=360,
                content=ft.Column([name_f, ft.Row([time_f, dose_f], wrap=True), note_f], tight=True, spacing=12),
            ),
            [
                text_button("Отмена", on_click=lambda e: self.page.pop_dialog()),
                ft.Button(
                    content="Сохранить",
                    on_click=lambda e: self.run_action(
                        lambda: self.store.add_pill(name_f.value, time_f.value, dose_f.value, note_f.value)
                        if pill is None else self.store.update_pill(pill["id"], name_f.value, time_f.value, dose_f.value, note_f.value),
                        dialog=True,
                    ),
                ),
            ],
        )

    def confirm_delete(self, title, text, action):
        self.open_dialog(
            title,
            ft.Text(text),
            [
                text_button("Отмена", on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content="Удалить", on_click=lambda e: self.run_action(action, dialog=True)),
            ],
        )

    def render_school(self):
        if self.selected_subject is not None:
            self.render_subject_detail(self.selected_subject)
            return

        tabs = ft.SegmentedButton(
            selected=[self.school_tab],
            segments=[
                ft.Segment(value="schedule", label=ft.Text("Расписание"), icon=ft.Icon(ft.Icons.CALENDAR_VIEW_DAY)),
                ft.Segment(value="subjects", label=ft.Text("Предметы"), icon=ft.Icon(ft.Icons.ANALYTICS_OUTLINED)),
            ],
            on_change=self.on_school_tab,
        )
        header = [ft.Text("Учёба", size=26, weight=ft.FontWeight.BOLD), tabs]

        if self.school_tab == "schedule":
            self.body.content = ft.Column(
                [*header, self.schedule_view()],
                spacing=14,
                expand=True,
            )
            self.page.update()
            if self.selected_day_idx > 0:
                self._scroll_to_day(self.selected_day_idx, animate=False)
        else:
            self.body.content = ft.Column(
                [*header, self.subjects_view()],
                spacing=16,
                expand=True,
                scroll=ft.ScrollMode.AUTO,
            )
            self.page.update()

    def on_school_tab(self, event):
        if event.control.selected:
            self.school_tab = next(iter(event.control.selected))
            self.render_school()

    def _estimate_day_height(self, idx):
        day = DAYS[idx]
        week_key = self.week.isoformat()
        lessons = []
        for n in self.store.lesson_numbers(week_key, day):
            cell = self.store.get(week_key, day, n)
            subj = lesson_subject(day, n, cell["subject"])
            if subj:
                lessons.append(cell)
        if not lessons:
            return 130.0
        total = 72.0
        for i, cell in enumerate(lessons):
            hw_lines = max(1, math.ceil(len(cell["hw"].strip()) / 28))
            row_h = 50.0 + (hw_lines - 1) * 16.0 + (34.0 if cell["grades"] else 0.0)
            total += max(68.0, row_h)
            if i < len(lessons) - 1:
                total += 24.0
        return total

    def _update_day_pills_ui(self):
        if not self.day_pill_refs:
            return
        for idx, (box, short_txt, num_txt) in enumerate(self.day_pill_refs):
            active = idx == self.selected_day_idx
            box.bgcolor = ft.Colors.PRIMARY if active else ft.Colors.SURFACE_CONTAINER_LOW
            short_txt.color = ft.Colors.ON_PRIMARY if active else ft.Colors.OUTLINE
            num_txt.color = ft.Colors.ON_PRIMARY if active else None
            box.update()

    def _scroll_to_day(self, idx, animate=True):
        if not self.schedule_list or not self.day_card_heights:
            return
        offset = sum(self.day_card_heights[:idx]) + idx * 14.0
        self.programmatic_scroll = True
        try:
            res = self.schedule_list.scroll_to(offset=offset, duration=260 if animate else 1)
            if hasattr(res, "__await__"):
                self.page.run_task(self._await_scroll, res)
            else:
                self.programmatic_scroll = False
        except Exception:
            self.programmatic_scroll = False

    async def _await_scroll(self, coro):
        try:
            await coro
        finally:
            self.programmatic_scroll = False

    def _on_schedule_scroll(self, event):
        if self.programmatic_scroll or not self.day_card_heights:
            return
        pixels = float(getattr(event, "pixels", 0) or 0)
        max_ext = float(getattr(event, "max_scroll_extent", 0) or 0)
        if max_ext > 0 and pixels >= max_ext - 14:
            new_idx = 5
        else:
            acc = 0.0
            new_idx = 0
            for idx, h in enumerate(self.day_card_heights):
                if pixels < acc + h * 0.55:
                    new_idx = idx
                    break
                acc += h + 14.0
                new_idx = idx
        if new_idx != self.selected_day_idx:
            self.selected_day_idx = new_idx
            self._update_day_pills_ui()

    def schedule_view(self):
        nav = ft.Row(
            [
                ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, on_click=lambda e: self.shift_week(-1)),
                ft.Text(week_label(self.week), weight=ft.FontWeight.BOLD, size=15, text_align=ft.TextAlign.CENTER, expand=True),
                ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, on_click=lambda e: self.shift_week(1)),
                text_button("Сегодня", on_click=self.go_today),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        short_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
        day_pills = []
        self.day_pill_refs = []
        for idx, short in enumerate(short_days):
            d = self.week + timedelta(days=idx)
            active = idx == self.selected_day_idx
            is_today = d == date.today()
            short_txt = ft.Text(
                short, size=13, weight=ft.FontWeight.BOLD,
                color=ft.Colors.ON_PRIMARY if active else ft.Colors.OUTLINE,
            )
            num_txt = ft.Text(
                str(d.day), size=15, weight=ft.FontWeight.BOLD,
                color=ft.Colors.ON_PRIMARY if active else None,
            )
            box = ft.Container(
                expand=True,
                padding=ft.Padding(0, 10, 0, 10),
                border_radius=12,
                bgcolor=ft.Colors.PRIMARY if active else ft.Colors.SURFACE_CONTAINER_LOW,
                border=ft.Border.all(1.5, ft.Colors.PRIMARY if is_today else ft.Colors.TRANSPARENT),
                on_click=lambda e, i=idx: self.select_day(i),
                content=ft.Column(
                    [short_txt, num_txt],
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )
            day_pills.append(box)
            self.day_pill_refs.append((box, short_txt, num_txt))

        self.day_card_heights = [self._estimate_day_height(i) for i in range(6)]
        cards = [self.day_card(i) for i in range(6)]
        self.schedule_list = ft.Column(
            controls=[*cards, ft.Container(height=300)],
            spacing=14,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            on_scroll=self._on_schedule_scroll,
        )

        return ft.Column(
            [
                nav,
                ft.Row(day_pills, spacing=8),
                self.schedule_list,
            ],
            spacing=12,
            expand=True,
        )

    def select_day(self, idx):
        self.selected_day_idx = idx
        self._update_day_pills_ui()
        self._scroll_to_day(idx, animate=True)

    def shift_week(self, amount):
        self.week += timedelta(weeks=amount)
        self.selected_day_idx = 0
        self.render_school()

    def go_today(self, event=None):
        today = date.today()
        self.week = monday_of(today)
        self.selected_day_idx = min(today.weekday(), 5)
        self.render_school()

    def open_lesson(self, week, day, number):
        self.week = monday_of(date.fromisoformat(week))
        self.selected_day_idx = DAYS.index(day) if day in DAYS else 0
        self.main_tab = 1
        self.nav.selected_index = 1
        self.selected_subject = None
        self.school_tab = "schedule"
        self.render()

    def day_card(self, index):
        day = DAYS[index]
        current_date = self.week + timedelta(days=index)
        week_key = self.week.isoformat()

        header = ft.Row(
            [
                ft.Text(f"{day}, {current_date.day} {MONTHS[current_date.month - 1]}", size=18, weight=ft.FontWeight.BOLD, expand=True),
                ft.Container(
                    visible=current_date == date.today(),
                    padding=ft.Padding(12, 4, 12, 4),
                    border_radius=8,
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.PRIMARY),
                    content=ft.Text("СЕГОДНЯ", color=ft.Colors.PRIMARY, size=11, weight=ft.FontWeight.BOLD),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        lessons = []
        for n in self.store.lesson_numbers(week_key, day):
            cell = self.store.get(week_key, day, n)
            subj = lesson_subject(day, n, cell["subject"])
            if subj:
                lessons.append((n, subj, cell))

        if not lessons:
            return self.card_box(
                ft.Column(
                    [
                        header,
                        ft.Container(padding=28, alignment=ft.Alignment(0, 0), content=ft.Text("Занятий нет", color=ft.Colors.OUTLINE)),
                    ],
                    spacing=10,
                )
            )

        rows = [header, ft.Divider(height=1)]
        for pos, (number, subject, cell) in enumerate(lessons):
            rows.append(self.lesson_row(week_key, day, number, subject, cell))
            if pos < len(lessons) - 1:
                rows.append(ft.Divider(height=1, color=ft.Colors.with_opacity(0.15, ft.Colors.OUTLINE)))
        return self.card_box(ft.Column(rows, spacing=12), padding=16)

    def lesson_row(self, week, day, number, subject, cell):
        start, end = BELLS[number]
        hw_clean = cell["hw"].strip()

        grade_badges = [
            ft.Container(
                width=28,
                height=28,
                border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.18, grade_color(item["value"])),
                border=ft.Border.all(1, grade_color(item["value"])),
                alignment=ft.Alignment(0, 0),
                content=ft.Text(str(item["value"]), size=13, weight=ft.FontWeight.BOLD, color=grade_color(item["value"])),
            )
            for item in cell["grades"]
        ]

        return ft.Row(
            [
                ft.Container(
                    width=52,
                    content=ft.Column(
                        [
                            ft.Text(f"0{number}", weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY, size=15),
                            ft.Text(start, size=11, color=ft.Colors.OUTLINE),
                            ft.Text(end, size=11, color=ft.Colors.OUTLINE),
                        ],
                        spacing=2,
                    ),
                ),
                ft.Column(
                    [
                        ft.Text(subject, size=15, weight=ft.FontWeight.BOLD),
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.SUBDIRECTORY_ARROW_RIGHT, size=15, color=ft.Colors.PRIMARY if hw_clean else ft.Colors.OUTLINE),
                                ft.Text(
                                    hw_clean or "Без задания",
                                    size=13,
                                    color=ft.Colors.ON_SURFACE if hw_clean else ft.Colors.OUTLINE,
                                    expand=True,
                                ),
                            ],
                            spacing=6,
                        ),
                        ft.Row(grade_badges, spacing=6, wrap=True) if grade_badges else ft.Container(),
                    ],
                    spacing=6,
                    expand=True,
                ),
                ft.Column(
                    [
                        ft.IconButton(
                            icon=ft.Icons.EDIT_NOTE,
                            icon_size=20,
                            tooltip="Домашнее задание",
                            on_click=lambda e, w=week, d=day, n=number: self.edit_homework(w, d, n),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.ADD_CHART,
                            icon_size=19,
                            tooltip="Оценки",
                            on_click=lambda e, w=week, d=day, n=number: self.edit_grade(w, d, n),
                        ),
                    ],
                    spacing=0,
                ),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    def edit_homework(self, week, day, number):
        cell = self.store.get(week, day, number)
        field = ft.TextField(label="Домашнее задание", value=cell["hw"], multiline=True, min_lines=3, max_lines=8, autofocus=True)

        def save(event):
            self.run_action(lambda: self.store.set_homework(week, day, number, field.value or ""), dialog=True)
            self.snack("Д/З сохранено")

        self.open_dialog(
            "Домашнее задание",
            ft.Container(width=420, content=field),
            [
                text_button("Отмена", on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content="Сохранить", on_click=save),
            ],
        )

    def confirm_delete_grade(self, week, day, number, grade_id, description, on_done=None):
        def confirm(event):
            self.page.pop_dialog()
            try:
                self.store.delete_grade(week, day, number, grade_id)
            except Exception as error:
                self.snack(str(error))
                return
            if on_done is not None:
                on_done()
            self.render_school()
            self.snack("Оценка удалена")

        self.open_dialog(
            "Удалить оценку?",
            ft.Text(f"Оценка {description} будет удалена."),
            [
                text_button("Отмена", on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content="Удалить", on_click=confirm),
            ],
        )

    def edit_grade(self, week, day, number):
        lesson_day = date.fromisoformat(week) + timedelta(days=DAYS.index(day))
        date_f = ft.TextField(label="Дата", value=lesson_day.isoformat(), hint_text="ГГГГ-ММ-ДД", width=150)
        grade_f = ft.TextField(label="Оценка (1–10)", keyboard_type=ft.KeyboardType.NUMBER, width=130)
        reason_f = ft.TextField(label="Комментарий", multiline=True, min_lines=2, max_lines=3)
        existing_list = ft.Column(spacing=6)
        editing_id = {"value": None}

        def load_for_edit(item):
            editing_id["value"] = item["id"]
            date_f.value = item["date"]
            grade_f.value = str(item["value"])
            reason_f.value = item["reason"]
            grade_f.label = "Оценка (правка)"
            date_f.error_text = grade_f.error_text = None
            self.page.update()

        def refresh_existing():
            existing_list.controls.clear()
            grades = self.store.get(week, day, number)["grades"]
            if not grades:
                existing_list.controls.append(ft.Text("Оценок нет", color=ft.Colors.OUTLINE, size=13))
            for item in grades:
                existing_list.controls.append(
                    ft.Row(
                        [
                            ft.Text(f"{item['date']} · {item['value']} · {item['reason'] or '—'}", size=13, expand=True),
                            ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_size=18, on_click=lambda e, r=item: load_for_edit(r)),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=18,
                                on_click=lambda e, r=item: self.confirm_delete_grade(
                                    week, day, number, r["id"], f"{r['value']} от {r['date']}",
                                    on_done=lambda gid=r["id"]: (editing_id.update({"value": None}) if editing_id["value"] == gid else None, refresh_existing()),
                                ),
                            ),
                        ]
                    )
                )

        def save(event):
            date_f.error_text = grade_f.error_text = None
            if not valid_grade(grade_f.value):
                grade_f.error_text = GRADE_ERROR
                self.page.update()
                return
            raw_date = (date_f.value or "").strip()
            try:
                date.fromisoformat(raw_date)
            except ValueError:
                date_f.error_text = DATE_ERROR
                self.page.update()
                return
            editing = editing_id["value"] is not None
            try:
                self.store.add_grade(week, day, number, grade_f.value, raw_date, reason_f.value or "", grade_id=editing_id["value"])
            except Exception as error:
                self.snack(str(error))
                return
            self.page.pop_dialog()
            self.render_school()
            self.snack("Оценка обновлена" if editing else "Оценка добавлена")

        refresh_existing()
        self.open_dialog(
            "Оценки за урок",
            ft.Container(
                width=440,
                content=ft.Column(
                    [
                        ft.Row([date_f, grade_f], wrap=True),
                        reason_f,
                        ft.Divider(),
                        existing_list,
                    ],
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=10,
                ),
            ),
            [
                text_button("Закрыть", on_click=lambda e: self.page.pop_dialog()),
                ft.Button(content="Сохранить", on_click=save),
            ],
        )

    def subjects_view(self):
        names = self.store.all_subjects()
        by_subject = self.store.grades_by_subject()
        cards = []
        tablet = self.is_tablet()

        for subject in names:
            values = [i["value"] for i in by_subject.get(subject, [])]
            count = len(values)
            avg = sum(values) / count if count else None
            accent = grade_color(avg) if avg is not None else ft.Colors.OUTLINE
            cards.append(
                ft.Container(
                    padding=14,
                    border_radius=14,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                    border=ft.Border.all(1, ft.Colors.with_opacity(0.12, ft.Colors.OUTLINE)),
                    on_click=lambda e, name=subject: self.open_subject(name),
                    content=ft.Row(
                        [
                            ft.Column(
                                [
                                    ft.Text(subject, weight=ft.FontWeight.BOLD, size=15),
                                    ft.Text(f"{count} {grades_word(count)}", size=13, color=ft.Colors.OUTLINE),
                                ],
                                spacing=3,
                                expand=True,
                            ),
                            ft.Container(
                                padding=ft.Padding(12, 6, 12, 6),
                                border_radius=10,
                                bgcolor=ft.Colors.with_opacity(0.15, accent),
                                content=ft.Text(f"{avg:.2f}" if avg is not None else "—", weight=ft.FontWeight.BOLD, color=accent),
                            ),
                            ft.Icon(ft.Icons.CHEVRON_RIGHT, color=ft.Colors.OUTLINE),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                )
            )

        if tablet:
            rows = []
            for i in range(0, len(cards), 2):
                chunk = cards[i:i+2]
                if len(chunk) == 1:
                    rows.append(ft.Row([chunk[0], ft.Container(expand=True)], spacing=12))
                else:
                    rows.append(ft.Row(chunk, spacing=12))
            return ft.Column(rows, spacing=10)

        return ft.Column(cards, spacing=10)

    def open_subject(self, subject):
        self.selected_subject = subject
        self.render_school()

    def grade_card(self, item):
        place = f"{item['day']}, урок №{item['number']} ({week_label(date.fromisoformat(item['week']))})"
        week, day, number = item["week"], item["day"], item["number"]
        color = grade_color(item["value"])
        return self.card_box(
            ft.Row(
                [
                    ft.Container(
                        width=44,
                        height=44,
                        border_radius=12,
                        bgcolor=ft.Colors.with_opacity(0.18, color),
                        border=ft.Border.all(1.5, color),
                        alignment=ft.Alignment(0, 0),
                        content=ft.Text(str(item["value"]), color=color, size=19, weight=ft.FontWeight.BOLD),
                    ),
                    ft.Column(
                        [
                            ft.Text(item["reason"] or "Без описания", size=15, weight=ft.FontWeight.W_600),
                            ft.Text(f"{item['date']} · {place}", size=12, color=ft.Colors.OUTLINE),
                        ],
                        spacing=3,
                        expand=True,
                    ),
                    ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, icon_size=18, on_click=lambda e, w=week, d=day, n=number: self.open_lesson(w, d, n)),
                    ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_size=18, on_click=lambda e, w=week, d=day, n=number: self.edit_grade(w, d, n)),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_size=18,
                        on_click=lambda e, it=item: self.confirm_delete_grade(
                            it["week"], it["day"], it["number"], it["id"], f"{it['value']} от {it['date']}",
                        ),
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=14,
        )

    def render_subject_detail(self, subject):
        grades = self.store.subject_grades(subject)
        values = [i["value"] for i in grades]
        avg = sum(values) / len(values) if values else None
        avg_text = f"{avg:.2f}" if avg is not None else "—"
        accent = grade_color(avg) if avg is not None else ft.Colors.PRIMARY

        target_f = ft.TextField(label="Цель (1–10)", hint_text="9", width=140, keyboard_type=ft.KeyboardType.NUMBER)
        plan_text = ft.Text("Введи целевой балл для расчёта необходимых оценок.", size=13, color=ft.Colors.OUTLINE)

        def calculate(event):
            try:
                target = parse_target(target_f.value)
            except ValueError:
                target_f.error_text = TARGET_ERROR
                target_f.update()
                return
            target_f.error_text = None
            target_f.update()
            threshold = target_threshold(target)
            plan = target_plan(values, target)
            if avg is not None and avg >= threshold - 1e-9:
                plan_text.value = f"Цель достигнута: текущий средний балл {avg:.2f} уже округляется до {math.floor(avg + 0.5)}."
            elif plan is None:
                plan_text.value = "Недостижимо в пределах 100 оценок."
            else:
                plan_text.value = f"Нужно получить ещё {len(plan)} {grades_word(len(plan))}: {', '.join(map(str, plan))}."
            plan_text.color = ft.Colors.PRIMARY
            plan_text.update()

        history = [self.grade_card(i) for i in reversed(grades)] or [ft.Text("Оценок пока нет.", color=ft.Colors.OUTLINE)]

        self.body.content = ft.Column(
            [
                text_button("Назад к предметам", icon=ft.Icons.ARROW_BACK, on_click=lambda e: self.back_to_subjects()),
                ft.Text(subject, size=26, weight=ft.FontWeight.BOLD),
                ft.Row(
                    [
                        self.card_box(
                            ft.Column([ft.Text("Средний балл", size=13, color=ft.Colors.OUTLINE), ft.Text(avg_text, size=28, weight=ft.FontWeight.BOLD, color=accent)], spacing=3),
                        ),
                        self.card_box(
                            ft.Column([ft.Text("Всего оценок", size=13, color=ft.Colors.OUTLINE), ft.Text(str(len(values)), size=28, weight=ft.FontWeight.BOLD)], spacing=3),
                        ),
                    ],
                    spacing=12,
                ),
                self.card_box(
                    ft.Column(
                        [
                            ft.Text("Калькулятор цели", weight=ft.FontWeight.BOLD, size=15),
                            ft.Row([target_f, ft.Button(content="Рассчитать", icon=ft.Icons.CALCULATE, on_click=calculate)], wrap=True),
                            plan_text,
                        ],
                        spacing=10,
                    )
                ),
                ft.Text("История оценок", size=18, weight=ft.FontWeight.BOLD),
                *history,
            ],
            spacing=14,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.update()

    def back_to_subjects(self):
        self.selected_subject = None
        self.school_tab = "subjects"
        self.render_school()


def check_auth_and_run(page: ft.Page):
    store = Store(data_path())

    page.title = "NEXUS // Дневник"
    page.padding = 0
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.CYAN)
    dark = store.theme() == "dark"
    page.theme_mode = ft.ThemeMode.DARK if dark else ft.ThemeMode.LIGHT
    page.bgcolor = ft.Colors.SURFACE

    def show_auth():
        page.navigation_bar = None
        page.on_resized = None
        page.controls.clear()
        auth_view = AuthView(page, store, on_success=init_main_app)
        page.add(auth_view.build())
        page.update()

    def init_main_app():
        DiaryApp(page, store=store, on_logout=show_auth)

    if store.get_current_user():
        init_main_app()
    else:
        show_auth()


def main(page: ft.Page):
    check_auth_and_run(page)


if __name__ == "__main__":
    ft.app(target=main)
