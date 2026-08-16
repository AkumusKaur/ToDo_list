"""
ToDo List — десктоп-версия (Tkinter).

Функции:
  - добавление / редактирование / удаление задач;
  - проверка названия на пустоту;
  - проверка формата даты ДД.ММ.ГГГГ (с учётом реального календаря);
  - приоритет из списка: высокий / средний / низкий;
  - дедлайны и напоминания (просроченные и «сегодня»), не чаще раза в день;
  - поиск по названию и описанию;
  - фильтры по статусу: все / активные / выполненные;
  - сортировка: по сроку / по приоритету / по статусу;
  - хранение в JSON с атомарной записью и бэкапом.
"""

import json
import os
import stat
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, date

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "tasks.json")
BACKUP_FILE = os.path.join(APP_DIR, "tasks_backup.json")

PRIORITY_KEYS = ["высокий", "средний", "низкий"]
PRIORITY_ORDER = {"высокий": 0, "средний": 1, "низкий": 2}
# синонимы из старой версии, чтобы не потерять приоритеты старых задач
PRIORITY_ALIASES = {
    "важно": "высокий",
    "обычно": "средний",
    "неважно": "низкий",
    "high": "высокий",
    "medium": "средний",
    "low": "низкий",
}

SORT_OPTIONS = ["по сроку", "по приоритету", "по статусу"]
FILTER_OPTIONS = ["все", "активные", "выполненные"]


def parse_date(text):
    """Проверка даты. Возвращает (ok, date_obj).
    Пустая строка — валидна (дедлайна нет)."""
    text = (text or "").strip()
    if not text:
        return True, None
    try:
        return True, datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        return False, None


def fmt_date(d):
    return d.strftime("%d.%m.%Y") if d else ""


def normalize_tasks(tasks):
    """Приводит старые задачи к новому формату (приоритеты, поля)."""
    for t in tasks:
        prio = t.get("priority", "средний")
        prio = PRIORITY_ALIASES.get(prio, prio)
        t["priority"] = prio if prio in PRIORITY_ORDER else "средний"
        t.setdefault("description", "")
        t.setdefault("due", "")
        t.setdefault("status", "active")
        t.setdefault("created", "")
    return tasks


def load_tasks():
    for path in (DATA_FILE, BACKUP_FILE):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return normalize_tasks(data)
            except Exception:
                continue
    return []


def save_tasks(tasks):
    """Атомарная запись: временный файл -> замена. При сбое — бэкап."""
    # 1) снять флаг «только чтение», если он есть
    try:
        if os.path.exists(DATA_FILE):
            os.chmod(DATA_FILE, stat.S_IWRITE)
    except Exception:
        pass
    # 2) атомарная запись через временный файл
    try:
        fd, tmp_path = tempfile.mkstemp(dir=APP_DIR, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, DATA_FILE)
        return True, None
    except OSError:
        # 3) запасной вариант — бэкап
        try:
            with open(BACKUP_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=2)
            return False, BACKUP_FILE
        except OSError:
            return False, None


class TodoApp:
    def __init__(self, root):
        self.root = root
        root.title("ToDo List — десктоп")
        root.geometry("920x580")
        root.minsize(720, 480)

        self.tasks = load_tasks()
        self._next_id = max((t.get("id", 0) for t in self.tasks), default=0) + 1
        for t in self.tasks:
            if not t.get("id"):
                t["id"] = self._next_id
                self._next_id += 1
        self.last_notified = {}  # id задачи -> дата последнего напоминания
        self.reminder_timer = None

        self._build_ui()
        self.refresh()
        self._schedule_reminders()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- интерфейс ----------
    def _build_ui(self):
        # --- форма добавления ---
        add = ttk.LabelFrame(self.root, text="Новая задача", padding=10)
        add.pack(fill="x", padx=10, pady=(10, 6))

        self.title_var = tk.StringVar()
        self.desc_var = tk.StringVar()
        self.prio_var = tk.StringVar(value="средний")
        self.date_var = tk.StringVar()

        ttk.Label(add, text="Название *").grid(row=0, column=0, sticky="w", pady=2)
        self.title_entry = ttk.Entry(add, textvariable=self.title_var, width=44)
        self.title_entry.grid(row=0, column=1, sticky="we", padx=6, pady=2)

        ttk.Label(add, text="Описание").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Entry(add, textvariable=self.desc_var, width=44).grid(row=1, column=1, sticky="we", padx=6, pady=2)

        ttk.Label(add, text="Приоритет").grid(row=0, column=2, sticky="w", padx=(14, 0), pady=2)
        ttk.Combobox(add, textvariable=self.prio_var, values=PRIORITY_KEYS,
                     state="readonly", width=12).grid(row=0, column=3, sticky="w", padx=6, pady=2)

        ttk.Label(add, text="Дедлайн (ДД.ММ.ГГГГ)").grid(row=1, column=2, sticky="w", padx=(14, 0), pady=2)
        self.date_entry = ttk.Entry(add, textvariable=self.date_var, width=16)
        self.date_entry.grid(row=1, column=3, sticky="w", padx=6, pady=2)

        ttk.Button(add, text="Добавить", command=self.add_task).grid(row=0, column=4, rowspan=2, padx=(14, 0))
        add.columnconfigure(1, weight=1)

        self.title_entry.bind("<Return>", self.add_task)
        self.date_entry.bind("<Return>", self.add_task)

        # --- панель поиска / фильтров / сортировки ---
        bar = ttk.Frame(self.root, padding=(10, 4))
        bar.pack(fill="x")

        ttk.Label(bar, text="Поиск:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self.refresh())
        ttk.Entry(bar, textvariable=self.search_var, width=22).pack(side="left", padx=6)

        ttk.Label(bar, text="Статус:").pack(side="left", padx=(14, 0))
        self.filter_var = tk.StringVar(value="все")
        ttk.Combobox(bar, textvariable=self.filter_var, values=FILTER_OPTIONS,
                     state="readonly", width=11).pack(side="left", padx=6)
        self.filter_var.trace_add("write", lambda *a: self.refresh())

        ttk.Label(bar, text="Сортировка:").pack(side="left", padx=(14, 0))
        self.sort_var = tk.StringVar(value="по сроку")
        ttk.Combobox(bar, textvariable=self.sort_var, values=SORT_OPTIONS,
                     state="readonly", width=13).pack(side="left", padx=6)
        self.sort_var.trace_add("write", lambda *a: self.refresh())

        # --- список задач ---
        cols = ("title", "priority", "due", "status")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("title", text="Задача")
        self.tree.heading("priority", text="Приоритет")
        self.tree.heading("due", text="Дедлайн")
        self.tree.heading("status", text="Статус")
        self.tree.column("title", width=420, anchor="w")
        self.tree.column("priority", width=110, anchor="center")
        self.tree.column("due", width=120, anchor="center")
        self.tree.column("status", width=120, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=6)

        self.tree.tag_configure("done", foreground="#999999")
        self.tree.tag_configure("overdue", foreground="#d93025", background="#fdecea")
        self.tree.tag_configure("today", foreground="#e8710a", background="#fff4e5")
        self.tree.tag_configure("prio_высокий", font=("Segoe UI", 10, "bold"))
        self.tree.tag_configure("prio_низкий", foreground="#666666")

        self.tree.bind("<Double-1>", self.edit_task)
        self.tree.bind("<Delete>", lambda e: self.delete_task())

        # --- кнопки действий ---
        btns = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        btns.pack(fill="x")
        ttk.Button(btns, text="Выполнено / Вернуть", command=self.toggle_status).pack(side="left", padx=2)
        ttk.Button(btns, text="Редактировать", command=self.edit_task).pack(side="left", padx=2)
        ttk.Button(btns, text="Удалить", command=self.delete_task).pack(side="left", padx=2)
        ttk.Button(btns, text="Очистить выполненные", command=self.clear_done).pack(side="left", padx=2)
        self.status_label = ttk.Label(btns, text="")
        self.status_label.pack(side="right")

    # ---------- действия ----------
    def add_task(self, event=None):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("Пустое название",
                                   "Название задачи не может быть пустым.", parent=self.root)
            self.title_entry.focus_set()
            return
        ok, due = parse_date(self.date_var.get())
        if not ok:
            messagebox.showwarning("Неверная дата",
                                   "Дата должна быть в формате ДД.ММ.ГГГГ,\n"
                                   "например 31.12.2025.", parent=self.root)
            self.date_entry.focus_set()
            return
        self.tasks.append({
            "id": self._next_id,
            "title": title,
            "description": self.desc_var.get().strip(),
            "priority": self.prio_var.get(),
            "due": fmt_date(due) if due else "",
            "status": "active",
            "created": datetime.now().isoformat(timespec="seconds"),
        })
        self._next_id += 1
        self._save_and_refresh()
        self.title_var.set("")
        self.desc_var.set("")
        self.date_var.set("")
        self.title_entry.focus_set()

    def edit_task(self, event=None):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Выберите задачу", "Сначала выберите задачу в списке.", parent=self.root)
            return
        task = self._find(int(sel[0]))
        if task:
            EditDialog(self.root, self, task)

    def toggle_status(self):
        sel = self.tree.selection()
        if not sel:
            return
        task = self._find(int(sel[0]))
        if task:
            task["status"] = "done" if task.get("status") != "done" else "active"
            self._save_and_refresh()

    def delete_task(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Выберите задачу", "Сначала выберите задачу в списке.", parent=self.root)
            return
        task = self._find(int(sel[0]))
        if not task:
            return
        if messagebox.askyesno("Удаление", f"Удалить задачу «{task.get('title')}»?", parent=self.root):
            self.tasks = [t for t in self.tasks if t.get("id") != task.get("id")]
            self._save_and_refresh()

    def clear_done(self):
        done = [t for t in self.tasks if t.get("status") == "done"]
        if not done:
            return
        if messagebox.askyesno("Очистка", f"Удалить {len(done)} выполненную(ых) задачу(и)?",
                               parent=self.root):
            self.tasks = [t for t in self.tasks if t.get("status") != "done"]
            self._save_and_refresh()

    # ---------- сортировка и отображение ----------
    def _sort_key(self, t):
        due = parse_date(t.get("due", ""))[1]
        due_val = due.toordinal() if due else 999999
        prio = PRIORITY_ORDER.get(t.get("priority", "средний"), 1)
        done = 1 if t.get("status") == "done" else 0
        created = t.get("created", "")
        mode = self.sort_var.get()
        if mode == "по приоритету":
            return (done, prio, due_val, created)
        if mode == "по статусу":
            return (done, prio, due_val, created)
        return (done, due_val, prio, created)  # по сроку (по умолчанию)

    def refresh(self):
        flt = self.filter_var.get()
        q = self.search_var.get().strip().lower()

        shown = []
        for t in self.tasks:
            if flt == "активные" and t.get("status") == "done":
                continue
            if flt == "выполненные" and t.get("status") != "done":
                continue
            if q and q not in t.get("title", "").lower() \
                   and q not in t.get("description", "").lower():
                continue
            shown.append(t)

        shown.sort(key=self._sort_key)

        self.tree.delete(*self.tree.get_children())
        today = date.today()
        for t in shown:
            due = parse_date(t.get("due", ""))[1]
            overdue = due is not None and due < today and t.get("status") != "done"
            due_today = due is not None and due == today and t.get("status") != "done"

            title = t.get("title", "")
            if t.get("description"):
                title = f"{title} — {t.get('description')}"
            status = "✓ выполнено" if t.get("status") == "done" else "активна"

            item = self.tree.insert("", "end",
                                    iid=str(t.get("id")),
                                    values=(title, t.get("priority", "средний"),
                                            t.get("due", "") or "—", status))
            tags = []
            if t.get("status") == "done":
                tags.append("done")
            elif overdue:
                tags.append("overdue")
            elif due_today:
                tags.append("today")
            tags.append("prio_" + t.get("priority", "средний"))
            self.tree.item(item, tags=tags)

        self.status_label.config(
            text=f"Всего: {len(self.tasks)} · показано: {len(shown)}")

    # ---------- сохранение и напоминания ----------
    def _find(self, tid):
        for t in self.tasks:
            if t.get("id") == tid:
                return t
        return None

    def _save_and_refresh(self):
        ok, backup = save_tasks(self.tasks)
        if not ok:
            if backup:
                messagebox.showwarning(
                    "Не удалось сохранить tasks.json",
                    f"Файл tasks.json занят или защищён от записи.\n"
                    f"Данные сохранены в {os.path.basename(backup)}.\n"
                    f"Закройте tasks.json в других программах и повторите действие.",
                    parent=self.root)
            else:
                messagebox.showerror("Ошибка сохранения",
                                     "Не удалось сохранить задачи ни в один файл!",
                                     parent=self.root)
        self.refresh()

    def _schedule_reminders(self):
        try:
            self._check_reminders()
        finally:
            self.reminder_timer = self.root.after(30000, self._schedule_reminders)

    def _check_reminders(self):
        today = date.today()
        for t in self.tasks:
            if t.get("status") == "done":
                continue
            due = parse_date(t.get("due", ""))[1]
            if due is None:
                continue
            tid = t.get("id")
            if self.last_notified.get(tid) == str(today):
                continue
            if due < today:
                messagebox.showwarning(
                    "Просрочено",
                    f"Задача «{t.get('title')}» просрочена (дедлайн был {t.get('due')}).")
                self.last_notified[tid] = str(today)
            elif due == today:
                messagebox.showinfo(
                    "Дедлайн сегодня",
                    f"Сегодня дедлайн задачи «{t.get('title')}».")
                self.last_notified[tid] = str(today)

    def _on_close(self):
        if self.reminder_timer:
            self.root.after_cancel(self.reminder_timer)
        self.root.destroy()


class EditDialog:
    def __init__(self, parent, app, task):
        self.app = app
        self.task = task

        self.win = tk.Toplevel(parent)
        self.win.title("Редактирование задачи")
        self.win.geometry("440x240")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()

        frm = ttk.Frame(self.win, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Название *").grid(row=0, column=0, sticky="w", pady=3)
        self.title_var = tk.StringVar(value=task.get("title", ""))
        ttk.Entry(frm, textvariable=self.title_var, width=42).grid(row=0, column=1, pady=3)

        ttk.Label(frm, text="Описание").grid(row=1, column=0, sticky="w", pady=3)
        self.desc_var = tk.StringVar(value=task.get("description", ""))
        ttk.Entry(frm, textvariable=self.desc_var, width=42).grid(row=1, column=1, pady=3)

        ttk.Label(frm, text="Приоритет").grid(row=2, column=0, sticky="w", pady=3)
        self.prio_var = tk.StringVar(value=task.get("priority", "средний"))
        ttk.Combobox(frm, textvariable=self.prio_var, values=PRIORITY_KEYS,
                     state="readonly", width=40).grid(row=2, column=1, pady=3)

        ttk.Label(frm, text="Дедлайн (ДД.ММ.ГГГГ)").grid(row=3, column=0, sticky="w", pady=3)
        self.date_var = tk.StringVar(value=task.get("due", ""))
        ttk.Entry(frm, textvariable=self.date_var, width=42).grid(row=3, column=1, pady=3)

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=2, pady=(14, 0), sticky="e")
        ttk.Button(btns, text="Сохранить", command=self.save).pack(side="left", padx=4)
        ttk.Button(btns, text="Отмена", command=self.win.destroy).pack(side="left", padx=4)

        self.win.bind("<Return>", lambda e: self.save())
        self.win.bind("<Escape>", lambda e: self.win.destroy())

    def save(self):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("Пустое название",
                                   "Название задачи не может быть пустым.", parent=self.win)
            return
        ok, due = parse_date(self.date_var.get())
        if not ok:
            messagebox.showwarning("Неверная дата",
                                   "Дата должна быть в формате ДД.ММ.ГГГГ.", parent=self.win)
            return
        self.task["title"] = title
        self.task["description"] = self.desc_var.get().strip()
        self.task["priority"] = self.prio_var.get()
        self.task["due"] = fmt_date(due) if due else ""
        self.app._save_and_refresh()
        self.win.destroy()


def main():
    root = tk.Tk()
    TodoApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
