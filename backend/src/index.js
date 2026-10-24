const { createApp } = require('./app');
const { env } = require('./config/env');

const app = createApp();

app.listen(env.port, env.host, () => {
  console.log(`Backend listening on http://${env.host}:${env.port}`);
});
