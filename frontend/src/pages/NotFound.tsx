import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="rounded-lg border bg-white p-6">
      <h2 className="mb-2 text-2xl font-bold">Page not found</h2>
      <p className="mb-4 text-sm text-gray-600">
        The page you requested does not exist.
      </p>
      <Link className="text-blue-600 hover:underline" to="/">
        Back to dashboard
      </Link>
    </div>
  );
}
