# SmartClass – Automatic Timetable Generator

SmartClass is a Flask-based academic timetable management system.

## Main rules

- Any number of classes/courses.
- Any number of divisions per class.
- Subjects are entered class-wise.
- A teacher can teach multiple classes, including FY/SY/TY.
- Global teacher clash prevention.
- Optional teacher availability by day.
- A lecture must fit completely inside the teacher's availability window.
- Practical sessions use two consecutive periods.
- Same theory subject is never placed back-to-back.
- Free periods are never placed in the middle of a division's timetable.
- Different divisions can run different lectures at the same time when teachers do not clash.
- Generated timetables can be saved and printed.
- Saved timetables appear on the dashboard.

## Run locally

```bash
python -m pip install -r requirements.txt
python app.py
```

Open:

`http://127.0.0.1:5000`

## Project flow

1. Create Project
2. Add Classes & Divisions
3. Add Subjects & Teachers class-wise
4. Set Teacher Availability
5. Set Timetable Settings
6. Review & Generate
7. Save / Print the generated timetable

## Important

The timetable generator is shared across the entire project. It does not generate FY,
SY and TY separately, so teacher clashes are checked globally.
