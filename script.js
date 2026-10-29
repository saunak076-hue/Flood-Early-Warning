try { require("dotenv").config(); } catch (e) {}
const express = require("express");
const cors = require("cors");
const path = require("path");

const app = express();
app.use(cors());
app.use(express.json());

app.get("/", (req, res) => res.sendFile(path.join(__dirname, "index.html")));

app.get("/health", (req, res) =>
  res.json({ status: "ok", project: "Team C: Flood Early Warning", stack: "node" })
);

app.get("/api/readings", (req, res) => {
  // TODO: Latest readings per zone
  res.status(501).json({ error: "Not implemented", todo: "Latest readings per zone" });
});

app.post("/api/predict", (req, res) => {
  // TODO: Body: features -> {risk, score}
  res.status(501).json({ error: "Not implemented", todo: "Body: features -> {risk, score}" });
});

app.get("/api/alerts", (req, res) => {
  // TODO: Active alerts
  res.status(501).json({ error: "Not implemented", todo: "Active alerts" });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Team C server running on http://localhost:${PORT}`));
