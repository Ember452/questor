import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import "./shared/theme/tokens.deepcode.css";
import "./shared/theme/tokens.reasonix.css";
import "./shared/theme/alias.css";

const root = document.getElementById("root");
if (!root) throw new Error("Questor web root is missing");
createRoot(root).render(<App />);
