import * as React from 'react'
import {
  sendSignInLinkToEmail,
  isSignInWithEmailLink,
  signInWithEmailLink,
  GoogleAuthProvider,
  signInWithPopup,
} from 'firebase/auth'
import { auth } from '../services/firebase'
import { useToast } from '@/components/ui/Toast'

export function AuthGate() {
  const [email, setEmail] = React.useState('')
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  // Magic link states
  const [linkSent, setLinkSent] = React.useState(false)
  const [isConfirmingLink, setIsConfirmingLink] = React.useState(false)
  const [needsEmailConfirmation, setNeedsEmailConfirmation] = React.useState(false)
  const [confirmEmail, setConfirmEmail] = React.useState('')

  const { toast } = useToast()

  // Handle URL detection on page load
  React.useEffect(() => {
    const handleEmailLinkSignIn = async () => {
      if (isSignInWithEmailLink(auth, window.location.href)) {
        const storedEmail = window.localStorage.getItem('emailForSignIn')
        if (storedEmail) {
          setIsConfirmingLink(true)
          setLoading(true)
          try {
            await signInWithEmailLink(auth, storedEmail, window.location.href)
            window.localStorage.removeItem('emailForSignIn')
            toast({
              title: 'Welcome Back',
              description: 'Successfully signed in via magic link.',
              type: 'success',
            })
            // Clean up the URL parameters so they don't linger
            window.history.replaceState({}, document.title, window.location.origin)
          } catch (err: any) {
            console.error(err)
            setError(err.message || 'Failed to sign in with magic link. The link may have expired or been used already.')
            setIsConfirmingLink(false)
          } finally {
            setLoading(false)
          }
        } else {
          // Cross-device/browser flow: storedEmail is empty
          setNeedsEmailConfirmation(true)
        }
      }
    }
    handleEmailLinkSignIn()
  }, [toast])

  const handleSendLink = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email) {
      setError('Please enter your email address.')
      return
    }

    setLoading(true)
    setError(null)

    const actionCodeSettings = {
      url: window.location.origin,
      handleCodeInApp: true,
    }

    try {
      await sendSignInLinkToEmail(auth, email, actionCodeSettings)
      window.localStorage.setItem('emailForSignIn', email)
      setLinkSent(true)
      toast({
        title: 'Magic Link Sent',
        description: `We've sent a secure login link to ${email}.`,
        type: 'success',
      })
    } catch (err: any) {
      console.error(err)
      let displayError = err.message || 'Authentication failed. Please check your credentials.'
      if (err.code === 'auth/invalid-email') {
        displayError = 'Please enter a valid email address.'
      }
      setError(displayError)
      toast({
        title: 'Authentication Error',
        description: displayError,
        type: 'error',
      })
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmEmailSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!confirmEmail) {
      setError('Please enter your email address to confirm.')
      return
    }

    setLoading(true)
    setError(null)
    setIsConfirmingLink(true)

    try {
      await signInWithEmailLink(auth, confirmEmail, window.location.href)
      window.localStorage.removeItem('emailForSignIn')
      toast({
        title: 'Welcome Back',
        description: 'Successfully signed in via magic link.',
        type: 'success',
      })
      window.history.replaceState({}, document.title, window.location.origin)
    } catch (err: any) {
      console.error(err)
      setError(err.message || 'Invalid email confirmation or expired link.')
      setIsConfirmingLink(false)
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleSignIn = async () => {
    setLoading(true)
    setError(null)
    const provider = new GoogleAuthProvider()

    try {
      await signInWithPopup(auth, provider)
      toast({
        title: 'Welcome Back',
        description: 'Successfully signed in with Google.',
        type: 'success',
      })
    } catch (err: any) {
      console.error(err)
      let displayError = err.message || 'Failed to sign in with Google.'
      if (err.code === 'auth/popup-closed-by-user') {
        displayError = 'Sign-in popup was closed before completion.'
      }
      setError(displayError)
      toast({
        title: 'Google Sign-In Error',
        description: displayError,
        type: 'error',
      })
    } finally {
      setLoading(false)
    }
  }

  // --- Render State 1: Validating/Authenticating standard link ---
  if (isConfirmingLink) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-zinc-50 font-sans text-zinc-800 dark:bg-zinc-950 dark:text-zinc-100 transition-colors duration-300">
        <div className="w-full max-w-md px-6 py-8 border border-zinc-200 dark:border-zinc-900 rounded-2xl bg-white/80 dark:bg-zinc-950/80 backdrop-blur-md shadow-2xl space-y-6 text-center">
          <div className="flex flex-col items-center space-y-4">
            <svg className="animate-spin h-10 w-10 text-blue-600 dark:text-blue-500" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <h1 className="text-xl font-bold tracking-tight text-zinc-900 dark:text-white">
              Securing Session
            </h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              Validating magic link, please wait a moment...
            </p>
          </div>
        </div>
      </div>
    )
  }

  // --- Render State 2: Cross-Device confirmation ---
  if (needsEmailConfirmation) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-zinc-50 font-sans text-zinc-800 dark:bg-zinc-950 dark:text-zinc-100 transition-colors duration-300">
        <div className="w-full max-w-md px-6 py-8 border border-zinc-200 dark:border-zinc-900 rounded-2xl bg-white/80 dark:bg-zinc-950/80 backdrop-blur-md shadow-2xl space-y-6">
          <div className="text-center space-y-2">
            <div className="inline-flex items-center justify-center h-12 w-12 rounded-full bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 mb-2">
              🔗
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">
              Confirm Email
            </h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
              We found your login link! To protect your account, please verify the email address you used to request this link.
            </p>
          </div>

          {error && (
            <div className="p-3.5 text-xs rounded-xl bg-rose-50 dark:bg-rose-950/30 text-rose-600 dark:text-rose-400 border border-rose-100 dark:border-rose-950/50 animate-pulse">
              ⚠️ {error}
            </div>
          )}

          <form onSubmit={handleConfirmEmailSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
                Email Address
              </label>
              <input
                type="email"
                required
                value={confirmEmail}
                onChange={(e) => setConfirmEmail(e.target.value)}
                placeholder="name@example.com"
                disabled={loading}
                className="w-full px-4 py-2.5 text-sm rounded-xl border border-zinc-200 dark:border-zinc-880 bg-white dark:bg-zinc-900 focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 dark:focus:border-blue-500 transition-all duration-205 disabled:opacity-50"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm transition-all duration-200 flex items-center justify-center shadow-lg hover:shadow-blue-600/10 cursor-pointer disabled:opacity-50"
            >
              {loading ? (
                <svg className="animate-spin h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                'Complete Sign In'
              )}
            </button>
          </form>

          <div className="text-center">
            <button
              onClick={() => {
                setNeedsEmailConfirmation(false)
                setError(null)
              }}
              className="text-xs font-semibold text-zinc-600 hover:text-blue-600 dark:text-zinc-400 dark:hover:text-blue-400 transition-colors duration-150 cursor-pointer"
            >
              ← Back to Sign In
            </button>
          </div>
        </div>
      </div>
    )
  }

  // --- Render State 3: Magic link sent page ---
  if (linkSent) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-zinc-50 font-sans text-zinc-800 dark:bg-zinc-950 dark:text-zinc-100 transition-colors duration-300">
        <div className="w-full max-w-md px-6 py-8 border border-zinc-200 dark:border-zinc-900 rounded-2xl bg-white/80 dark:bg-zinc-950/80 backdrop-blur-md shadow-2xl space-y-6 text-center">
          <div className="space-y-4">
            <div className="inline-flex items-center justify-center h-14 w-14 rounded-full bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 text-2xl animate-bounce">
              ✉️
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">
              Check Your Inbox
            </h1>
            <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed px-2">
              We have emailed a secure, passwordless magic link to <strong className="text-zinc-900 dark:text-zinc-200 font-semibold">{email}</strong>.
              Click the link in the email to log in instantly.
            </p>
          </div>

          <div className="p-4 rounded-xl bg-zinc-50 dark:bg-zinc-900/60 border border-zinc-100 dark:border-zinc-900 text-xs text-zinc-500 dark:text-zinc-400 space-y-1.5 text-left">
            <p className="font-semibold text-zinc-700 dark:text-zinc-300">💡 Can't find the email?</p>
            <ul className="list-disc pl-4 space-y-1">
              <li>Check your Spam, Junk, or Promotions folder.</li>
              <li>Wait a couple of minutes for delivery.</li>
              <li>Make sure you typed the correct address.</li>
            </ul>
          </div>

          <div className="pt-2">
            <button
              onClick={() => {
                setLinkSent(false)
                setError(null)
              }}
              className="text-xs font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 transition-colors duration-150 cursor-pointer"
            >
              ← Try another email address
            </button>
          </div>
        </div>
      </div>
    )
  }

  // --- Render State 4: Default input email form ---
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-zinc-50 font-sans text-zinc-800 dark:bg-zinc-950 dark:text-zinc-100 transition-colors duration-300">
      <div className="w-full max-w-md px-6 py-8 border border-zinc-200 dark:border-zinc-900 rounded-2xl bg-white/80 dark:bg-zinc-950/80 backdrop-blur-md shadow-2xl space-y-6">
        <div className="text-center space-y-2">
          <h1 className="text-2xl font-bold tracking-tight text-blue-600 dark:text-blue-500">
            Chatbot GCP
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
            Enter your email to receive a passwordless magic sign-in link
          </p>
        </div>

        {error && (
          <div className="p-3.5 text-xs rounded-xl bg-rose-50 dark:bg-rose-950/30 text-rose-600 dark:text-rose-400 border border-rose-100 dark:border-rose-950/50 animate-pulse">
            ⚠️ {error}
          </div>
        )}

        <form onSubmit={handleSendLink} className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
              Email Address
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
              disabled={loading}
              className="w-full px-4 py-2.5 text-sm rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 focus:outline-hidden focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 dark:focus:border-blue-500 transition-all duration-200 disabled:opacity-50"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-medium text-sm transition-all duration-200 flex items-center justify-center shadow-lg hover:shadow-blue-600/10 cursor-pointer disabled:opacity-50"
          >
            {loading ? (
              <svg className="animate-spin h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
                'Send Magic Link'
            )}
          </button>
        </form>

        <div className="relative flex items-center justify-center">
          <div className="absolute inset-0 border-t border-zinc-200 dark:border-zinc-900" />
          <span className="relative px-3 text-xs bg-white dark:bg-zinc-950 text-zinc-400 dark:text-zinc-500 uppercase tracking-wider font-semibold">
            Or
          </span>
        </div>

        <button
          type="button"
          onClick={handleGoogleSignIn}
          disabled={loading}
          className="w-full py-2.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-850 text-zinc-700 dark:text-zinc-200 font-medium text-sm transition-all duration-200 flex items-center justify-center gap-2.5 shadow-sm hover:shadow-md cursor-pointer disabled:opacity-50"
        >
          <svg className="h-4.5 w-4.5" viewBox="0 0 24 24">
            <path
              fill="#EA4335"
              d="M5.266 9.765A7.077 7.077 0 0 1 12 4.909c1.69 0 3.218.6 4.418 1.582L19.91 3C17.782 1.145 15.055 0 12 0 7.273 0 3.19 2.7 1.24 6.645l4.027 3.12z"
            />
            <path
              fill="#4285F4"
              d="M16.04 15.34c-1.07.727-2.455 1.16-4.04 1.16-2.927 0-5.39-1.973-6.264-4.636L1.71 14.99C3.655 18.936 7.736 21.6 12 21.6c3.136 0 5.864-1.036 7.827-2.827l-3.786-3.433z"
            />
            <path
              fill="#FBBC05"
              d="M5.736 11.864a6.98 6.98 0 0 1 0-2.128L1.71 6.609a11.96 11.96 0 0 0 0 10.782l4.027-3.527z"
            />
            <path
              fill="#34A853"
              d="M23.49 12.273c0-.818-.082-1.609-.218-2.373H12v4.582h6.49a5.618 5.618 0 0 1-2.427 3.709l3.786 3.433c2.209-2.036 3.64-5.073 3.64-9.35z"
            />
          </svg>
          Sign In with Google
        </button>
      </div>
    </div>
  )
}
