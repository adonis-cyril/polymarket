# Migration history

These SQL files were originally written for Supabase. The consolidated schema for local PostgreSQL is in `scripts/init_db.sql` (applied automatically by `docker-compose up` or `python -c "from data import db; db.init_db()"`).

Individual migrations are kept here for reference. RLS policies (`003`) and Realtime (`004`) are not applied locally.
