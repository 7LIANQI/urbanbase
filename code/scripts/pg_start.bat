@echo off
REM Start local PostgreSQL (portable binaries under D:\PostgreSQL17)
"D:\PostgreSQL17\pgsql\bin\pg_ctl.exe" -D "D:\PostgreSQL17\data" -l "D:\PostgreSQL17\pg.log" start
