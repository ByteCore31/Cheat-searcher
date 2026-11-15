@echo off
title Cheat Search
python "%~dp0cheat_search.py"
if %errorlevel% neq 0 pause
