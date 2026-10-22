function getHealth(_req, res) {
  res.json({
    status: 'ok',
    service: 'personalized-travel-itinerary-planner',
  });
}

module.exports = { getHealth };
