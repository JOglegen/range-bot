/**
 * Netlify Function: alpaca.js
 * Proxies requests to Alpaca paper API — keys stay server-side.
 *
 * Endpoints (?endpoint= query param):
 *   account    GET /v2/account
 *   positions  GET /v2/positions
 *   orders     GET /v2/orders?status=all&limit=30
 *   portfolio  GET /v2/account/portfolio/history?period=1M&timeframe=1D
 *   bars       GET /v2/stocks/{sym}/bars  (?sym=AAPL)
 */

const https = require("https");

const TRADE = "https://paper-api.alpaca.markets/v2";
const DATA  = "https://data.alpaca.markets/v2";

function httpsGet(url, headers) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => resolve({ status: res.statusCode, body }));
    });
    req.on("error", reject);
    req.setTimeout(15000, () => { req.destroy(); reject(new Error("timeout")); });
  });
}

exports.handler = async (event) => {
  const key    = process.env.ALPACA_API_KEY;
  const secret = process.env.ALPACA_API_SECRET;

  if (!key || !secret) {
    return {
      statusCode: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: "Alpaca credentials not set in Netlify env vars. Go to Site configuration → Environment variables." }),
    };
  }

  const headers = {
    "APCA-API-KEY-ID":     key,
    "APCA-API-SECRET-KEY": secret,
    "accept":              "application/json",
  };

  const params  = event.queryStringParameters || {};
  const endpoint = params.endpoint || "account";

  let url;
  switch (endpoint) {
    case "account":   url = `${TRADE}/account`; break;
    case "positions": url = `${TRADE}/positions`; break;
    case "orders":    url = `${TRADE}/orders?status=all&limit=30&direction=desc`; break;
    case "portfolio": url = `${TRADE}/account/portfolio/history?period=1M&timeframe=1D`; break;
    case "bars": {
      const sym = (params.sym || "AAPL").toUpperCase();
      url = `${DATA}/stocks/${sym}/bars?timeframe=1Day&limit=30&feed=iex`;
      break;
    }
    default:
      return { statusCode: 400, body: JSON.stringify({ error: `Unknown endpoint: ${endpoint}` }) };
  }

  try {
    const { status, body } = await httpsGet(url, headers);
    return {
      statusCode: status,
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
      },
      body,
    };
  } catch (err) {
    return {
      statusCode: 500,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ error: err.message }),
    };
  }
};
