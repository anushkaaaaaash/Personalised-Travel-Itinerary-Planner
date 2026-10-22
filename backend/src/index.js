const express = require('express');
const cors = require('cors');
const { env } = require('./config/env');
const routes = require('./routes');

const app = express();

app.use(
  cors({
    origin: env.clientOrigin,
  })
);
app.use(express.json());
app.use('/api', routes);

app.listen(env.port, () => {
  console.log(`Backend listening on http://localhost:${env.port}`);
});
