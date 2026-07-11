import os
import resend

resend.api_key = os.getenv("RESEND_API_KEY")


def send_clips_ready_email(to_email: str, job_id: str, clip_count: int):
    """Send email when clips are ready. Never raises — failures are logged only."""
    dashboard_url = f"http://localhost:5173/dashboard/{job_id}"

    try:
        resend.Emails.send({
            "from": "ClipForge AI <onboarding@resend.dev>",
            "to": to_email,
            "subject": f"✂️ Your {clip_count} Telugu clips are ready!",
            "html": f"""
            <div style="font-family: Arial, sans-serif; max-width: 560px;
                        margin: 0 auto; background: #0a0a0f;
                        color: #f0f0f8; padding: 40px; border-radius: 12px;">

                <div style="text-align: center; margin-bottom: 32px;">
                    <span style="font-size: 40px;">⚡</span>
                    <h1 style="color: #f0f0f8; font-size: 24px;
                               margin: 12px 0 4px;">
                        Your clips are ready!
                    </h1>
                    <p style="color: #6b6b80; font-size: 14px; margin: 0;">
                        ClipForge AI finished processing your video
                    </p>
                </div>

                <div style="background: #111118; border: 1px solid #2a2a3a;
                            border-radius: 10px; padding: 20px;
                            text-align: center; margin-bottom: 28px;">
                    <p style="color: #6b6b80; font-size: 13px; margin: 0 0 6px;">
                        We found
                    </p>
                    <p style="color: #a78bfa; font-size: 36px;
                               font-weight: 700; margin: 0;">
                        {clip_count}
                    </p>
                    <p style="color: #6b6b80; font-size: 13px; margin: 6px 0 0;">
                        viral-ready Telugu clips
                    </p>
                </div>

                <div style="text-align: center; margin-bottom: 32px;">
                    <a href="{dashboard_url}"
                       style="display: inline-block; background: #7c3aed;
                              color: white; text-decoration: none;
                              padding: 14px 32px; border-radius: 8px;
                              font-size: 15px; font-weight: 600;">
                        View my clips →
                    </a>
                </div>

                <p style="color: #3a3a4a; font-size: 11px;
                           text-align: center; margin: 0;">
                    Built for Telugu creators · Powered by Gemini + Sarvam AI
                </p>
            </div>
            """
        })
        print(f"[email] Sent clips ready email to {to_email}")
    except Exception as e:
        print(f"[email] Failed to send email: {e}")
