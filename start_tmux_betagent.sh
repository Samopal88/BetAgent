#!/bin/bash

SESSION="betagent"

tmux has-session -t $SESSION 2>/dev/null
if [ $? -eq 0 ]; then
  echo "Session $SESSION already exists"
  exit 0
fi

tmux new-session -d -s $SESSION -n shell

tmux new-window -t $SESSION:1 -n api
tmux send-keys -t $SESSION:1 'cd /root/betagent && source venv/bin/activate && uvicorn api.app:app --host 0.0.0.0 --port 8010' C-m

tmux new-window -t $SESSION:2 -n bot
tmux send-keys -t $SESSION:2 'cd /root/betagent && source venv/bin/activate && python3 tg_bot.py' C-m

tmux new-window -t $SESSION:3 -n web
tmux send-keys -t $SESSION:3 'cd /root/betagent && source venv/bin/activate && python3 web_panel.py' C-m

tmux new-window -t $SESSION:4 -n logs
tmux send-keys -t $SESSION:4 'cd /root/betagent && tail -f cron.log' C-m

tmux attach -t $SESSION
