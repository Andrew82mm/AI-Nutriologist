import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Showcase from "./Showcase";
import "./app.css";

// #showcase renders the marketing composition (three phones) instead of the app.
const Root = window.location.hash === "#showcase" ? Showcase : App;

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
