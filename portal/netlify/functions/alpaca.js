/**
 * Netlify Function: alpaca.js
 * Proxies requests to the Alpaca paper trading API.
 * ALPACA_API_KEY and ALPACA_API_SECRET are set as Netlify env vars — never
 * sent to the browser.
 *
 * Endpoints supported (via ?endpoint= query param):
 *   account          GET /v2/account
 *   positions        GET /v2/positions
 *   orders           GET /v2/orders?status=all&limit=20
 *   portfolio        GET /v2/account/portfolio/history
 *   bars?sym=AAPL    GET /v2/stocks/AAPL/bars (via data API)
 */

const TRADE = "https://paper-api.alpaca.markets/v2";
const DATA  = "https://data.alpaca.markets/v2";

exports.handler = async (event) => {
  const key    = process.env.ALPACA_API_KEY;
  const secret = process.env.ALPACA_API_SECRET;

  if (!key || !secret) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: "Alpaca credentials not configured in Netlify env vars." }),
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
    case "account":
      url = `${TRADE}/account`;
      break;
    case "positions":
      url = `${TRADE}/positions`;
      break;
    case "orders":
      url = `${TRADE}/orders?status=all&limit=30&direction=desc`;
      break;
    case "portfolio":
      url = `${TRADE}/account/portfolio/history?period=1M&timeframe=1D`;
      break;
    case "bars": {
      const sym = (params.sym || "AAPL").toUpperCase();
      url = `${DATA}/stocks/${sym}/bars?timeframe=1Day&limit=30&feed=iex`;
      break;
    }
    default:
      return { statusCode: 400, body: JSON.stringify({ error: `Unknown endpoint: ${endpoint}` }) };
  }

  try {
    const res  = await fetch(url, { headers });
    const body = await res.text();
    return {
      statusCode: res.status,
      headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" },
      body,
    };
  } catch (err) {
    return {
      statusCode: 500,
      body: JSON.stringify({ error: err.message }),
    };
  }
};
