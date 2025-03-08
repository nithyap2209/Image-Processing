from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from PIL import Image, ImageOps
import os
import zipfile
import io
import shutil
import uuid
import time
from rembg import remove

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

# Create necessary folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

def allowed_image_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

def allowed_zip_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'zip'

def get_file_extension(format_name):
    format_map = {
        'png': 'png',
        'jpg': 'jpg',
        'jpeg': 'jpg',
        'webp': 'webp',
        'gif': 'gif',
        'bmp': 'bmp'
    }
    return format_map.get(format_name.lower(), 'png')

def process_image(image_path, options):
    # Open image with Pillow
    img = Image.open(image_path)
    
    # Handle EXIF orientation tags
    img = ImageOps.exif_transpose(img)
    
    # Convert RGBA if needed for certain operations
    if img.mode != 'RGBA' and (options['changeBackground'] or options['format'].lower() == 'png'):
        img = img.convert('RGBA')
    
    # Process background if requested
    if options['changeBackground']:
        if options['backgroundType'] == 'transparent':
            # Remove background
            img = remove(img)  # Using rembg library for background removal
        elif options['backgroundType'] == 'color':
            # Change background color
            img = remove(img)
            
            # Create a new image with the chosen background color
            background_color = options['backgroundColor'].lstrip('#')
            bg_color = tuple(int(background_color[i:i+2], 16) for i in (0, 2, 4))
            
            # Add alpha channel to make a 4-tuple
            bg_color = bg_color + (255,)
            
            # Create new background image
            background = Image.new('RGBA', img.size, bg_color)
            
            # Composite the foreground with the background
            background.paste(img, (0, 0), img)
            img = background
    
    # Handle format change
    output_format = options['format'].upper() if options['changeFormat'] else img.format
    
    # Ensure PNG for transparent images
    if img.mode == 'RGBA' and output_format in ['JPEG', 'JPG']:
        # Convert to RGB for JPEG (which doesn't support transparency)
        img = img.convert('RGB')
        output_format = 'JPEG'
    
    # Compress if requested
    if options['compress']:
        # Create an in-memory buffer for the image
        buffer = io.BytesIO()
        if output_format == 'PNG':
            # For PNG images
            img.save(buffer, format='PNG', optimize=True, compress_level=9)
        elif output_format in ['JPEG', 'JPG']:
            # For JPEG images
            img.save(buffer, format=output_format, quality=50, optimize=True)
        elif output_format == 'GIF':
            # For GIF images
            img.save(buffer, format='GIF', optimize=True)
        elif output_format == 'BMP':
            # For BMP images
            img.save(buffer, format='BMP', optimize=True)
        else:
            # For other formats
            img.save(buffer, format=output_format, optimize=True)
        buffer.seek(0)
        img = Image.open(buffer)
    
    return img, output_format

@app.route('/process_image', methods=['POST'])
def process_single_image():
    # Check if image file is included in the request
    if 'image' not in request.files:
        return jsonify({'error': 'No image file found'}), 400
    
    file = request.files['image']
    
    if file.filename == '':
        return jsonify({'error': 'No image selected'}), 400
    
    if not allowed_image_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    # Parse processing options
    options = {
        'changeBackground': request.form.get('changeBackground') == 'true',
        'backgroundType': request.form.get('backgroundType'),
        'backgroundColor': request.form.get('backgroundColor', '#ffffff'),
        'changeFormat': request.form.get('changeFormat') == 'true',
        'format': request.form.get('format', 'png'),
        'compress': request.form.get('compress') == 'true'
    }
    
    # Generate a unique filename
    unique_id = str(uuid.uuid4())
    original_extension = file.filename.rsplit('.', 1)[1].lower()
    temp_filename = f"{unique_id}.{original_extension}"
    temp_filepath = os.path.join(UPLOAD_FOLDER, temp_filename)
    
    # Save the uploaded file temporarily
    file.save(temp_filepath)
    
    try:
        # Process the image
        processed_img, output_format = process_image(temp_filepath, options)
        
        # Determine output filename and extension
        output_extension = get_file_extension(options['format'] if options['changeFormat'] else original_extension)
        output_filename = f"{unique_id}_processed.{output_extension}"
        output_filepath = os.path.join(PROCESSED_FOLDER, output_filename)
        
        # Save the processed image
        processed_img.save(output_filepath, format=output_format)
        
        # Remove the temp file
        os.remove(temp_filepath)
        
        # Return the processed image as a file
        return send_file(output_filepath, as_attachment=True, download_name=f"processed_{file.filename.rsplit('.', 1)[0]}.{output_extension}")
    
    except Exception as e:
        # Clean up temp file
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
        return jsonify({'error': str(e)}), 500

@app.route('/process_zip', methods=['POST'])
def process_zip_file():
    # Check if zip file is included in the request
    if 'zip' not in request.files:
        return jsonify({'error': 'No zip file found'}), 400
    
    file = request.files['zip']
    
    if file.filename == '':
        return jsonify({'error': 'No zip file selected'}), 400
    
    if not allowed_zip_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    # Parse processing options
    options = {
        'changeBackground': request.form.get('changeBackground') == 'true',
        'backgroundType': request.form.get('backgroundType'),
        'backgroundColor': request.form.get('backgroundColor', '#ffffff'),
        'changeFormat': request.form.get('changeFormat') == 'true',
        'format': request.form.get('format', 'png'),
        'compress': request.form.get('compress') == 'true'
    }
    
    # Generate unique IDs for the processing
    unique_id = str(uuid.uuid4())
    temp_zip_path = os.path.join(UPLOAD_FOLDER, f"{unique_id}.zip")
    temp_extract_dir = os.path.join(UPLOAD_FOLDER, unique_id)
    processed_zip_path = os.path.join(PROCESSED_FOLDER, f"{unique_id}_processed.zip")
    
    # Create extraction directory
    os.makedirs(temp_extract_dir, exist_ok=True)
    
    # Save the uploaded zip file temporarily
    file.save(temp_zip_path)
    
    try:
        # Extract zip file
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_dir)
        
        # Process each image in the extracted directory
        processed_files = []
        
        for root, _, files in os.walk(temp_extract_dir):
            for filename in files:
                if allowed_image_file(filename):
                    file_path = os.path.join(root, filename)
                    
                    try:
                        print(f"Processing file: {file_path}")
                        # Process the image
                        processed_img, output_format = process_image(file_path, options)
                        
                        # Determine output path
                        rel_path = os.path.relpath(file_path, temp_extract_dir)
                        
                        # Change extension if format is changed
                        if options['changeFormat']:
                            output_extension = get_file_extension(options['format'])
                            rel_path = os.path.splitext(rel_path)[0] + '.' + output_extension
                        
                        processed_path = os.path.join(temp_extract_dir, "_processed", rel_path)
                        
                        # Create directory if it doesn't exist
                        os.makedirs(os.path.dirname(processed_path), exist_ok=True)
                        
                        # Save processed image
                        processed_img.save(processed_path, format=output_format)
                        processed_files.append(rel_path)
                    except Exception as e:
                        print(f"Error processing {filename}: {str(e)}")
        
        # Create new zip file with processed images
        with zipfile.ZipFile(processed_zip_path, 'w') as zip_ref:
            processed_dir = os.path.join(temp_extract_dir, "_processed")
            for root, _, files in os.walk(processed_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, processed_dir)
                    zip_ref.write(file_path, rel_path)
        
        # Clean up temporary files and directories
        os.remove(temp_zip_path)
        shutil.rmtree(temp_extract_dir)
        
        # Return the processed zip file
        return send_file(processed_zip_path, as_attachment=True, download_name=f"processed_{file.filename}")
    
    except Exception as e:
        # Clean up temporary files and directories
        if os.path.exists(temp_zip_path):
            os.remove(temp_zip_path)
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)
        
        print(f"Error processing zip file: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Route to serve static files (for frontend)
@app.route('/', methods=['GET'])
def serve_frontend():
    return send_file('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204

if __name__ == '__main__':
    app.run(debug=True, port=5000)