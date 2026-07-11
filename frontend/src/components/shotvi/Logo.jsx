import React from "react";
import { Link } from "react-router-dom";

export const Logo = ({ size = "md", withText = true, className = "" }) => {
  const dim = size === "sm" ? 24 : size === "lg" ? 40 : 32;
  return (
    <Link
      to="/"
      className={`flex items-center gap-2.5 no-underline ${className}`}
    >
      <div
        className="relative flex items-center justify-center rounded-lg"
        style={{
          width: dim,
          height: dim,
          background:
            "linear-gradient(135deg,#7c3aed 0%,#c026d3 55%,#f97316 100%)",
          boxShadow: "0 6px 24px rgba(124,58,237,0.35)",
        }}
      >
        <svg
          width={dim * 0.55}
          height={dim * 0.55}
          viewBox="0 0 24 24"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <path d="M6 4L18 12L6 20V4Z" fill="white" />
        </svg>
      </div>
      {withText && (
        <span
          className="font-display font-bold text-white"
          style={{
            fontSize: size === "sm" ? 16 : size === "lg" ? 26 : 20,
            letterSpacing: "-0.02em",
          }}
        >
          Shotvi
        </span>
      )}
    </Link>
  );
};

export default Logo;
