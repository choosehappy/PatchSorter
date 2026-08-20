export default function StepComplete() {
    return (
        <div className="text-center py-4">
            <div style={{ fontSize: '3.5rem' }}>✅</div>
            <h5 className="mt-3 mb-2">Upload Processing Started</h5>
            <p className="text-muted mb-0">
                Your files are being processed on the server. This may take several minutes
                depending on the number and size of images.
            </p>
        </div>
    )
}
