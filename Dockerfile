# The site is static: there is nothing to build, only web/ to serve. Every
# rig in tools/ and everything under blender/ is development-side and stays
# out of the image.
FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY web/ /usr/share/nginx/html/

EXPOSE 8080
