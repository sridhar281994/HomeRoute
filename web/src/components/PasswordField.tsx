import { useId, useState } from "react";

export default function PasswordField(props: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoComplete?: string;
}) {
  const id = useId();
  const [show, setShow] = useState(false);
  const type = show ? "text" : "password";

  return (
    <div>
      <label className="muted" htmlFor={id}>
        {props.label}
      </label>
      <div className="input-icon-wrap">
        <input
          id={id}
          type={type}
          value={props.value}
          placeholder={props.placeholder}
          autoComplete={props.autoComplete}
          onChange={(e) => props.onChange(e.target.value)}
        />
        <button
          type="button"
          className="icon-btn"
          aria-label={show ? "Hide password" : "Show password"}
          onClick={() => setShow((v) => !v)}
        >
          {show ? (
            // eye (visible)
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path
                d="M2.3 12s3.6-7 9.7-7 9.7 7 9.7 7-3.6 7-9.7 7-9.7-7-9.7-7Z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M12 15.4a3.4 3.4 0 1 0 0-6.8 3.4 3.4 0 0 0 0 6.8Z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          ) : (
            // eye-off (crossed)
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path
                d="M10.6 5.2A10 10 0 0 1 12 5c6.1 0 9.7 7 9.7 7a18.2 18.2 0 0 1-3 4.1"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M14.2 14.2a3.4 3.4 0 0 1-4.4-4.4"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M4.3 4.3 19.7 19.7"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M6.1 6.1C3.4 8.1 2.3 12 2.3 12s3.6 7 9.7 7c1.4 0 2.7-.3 3.9-.7"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}

