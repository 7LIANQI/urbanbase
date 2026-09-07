@echo off
REM One-time init: create data dir + superuser (run only if data dir missing)
if not exist "D:\PostgreSQL17\data" (
    echo postgres> "D:\PostgreSQL17\pwfile.txt"
    "D:\PostgreSQL17\pgsql\bin\initdb.exe" -D "D:\PostgreSQL17\data" -U postgres -A scram-sha-256 --pwfile="D:\PostgreSQL17\pwfile.txt" -E UTF8 --locale=C
)
