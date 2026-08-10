module.exports = {
  apps : [
    {
      name: "jarvis",
      interpreter: ".venv/bin/python3",
      script: "app/server.py",
    },
    {
      name: "jarvis-watcher",
      interpreter: ".venv/bin/python3",
      script: "app/watcher_service.py",
    },
  ],
};
