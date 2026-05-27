// pm2.config.js — Deploy JobHunter as a PM2 process on your VPS
// Usage: pm2 start pm2.config.js

module.exports = {
  apps: [
    {
      name: "jobhunter",
      script: "main.py",
      interpreter: "python3",
      args: "daemon",
      cwd: "/root/jobhunter",   // adjust to your VPS path
      watch: false,
      autorestart: true,
      max_restarts: 5,
      restart_delay: 10000,     // 10s between restarts
      env: {
        PYTHONUNBUFFERED: "1",
        LOG_LEVEL: "INFO"
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file: "./logs/pm2-out.log",
      error_file: "./logs/pm2-err.log",
      merge_logs: true
    }
  ]
}
