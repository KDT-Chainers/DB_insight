@echo off
chcp 65001 > nul
echo ============================================================
echo  야간 오케스트레이터 시작 (23:00 ~ 07:30)
echo  종료: 07:20 자동 체크포인트 저장
echo  재개: 09:00 에 start_morning_resume.bat 실행
echo ============================================================
echo.

cd /d "%~dp0App\backend"
python scripts\overnight_orchestrator.py

echo.
echo ============================================================
echo  [완료] overnight_orchestrator.py 종료
echo  09:00 이후 start_morning_resume.bat 을 실행하세요.
echo ============================================================
pause
